"""메모리 가격 전망·리서치 요약 → data/memory_outlook.json

 1. TrendForce 보도자료 (presscenter, 키워드 DRAM/NAND/HBM/SSD/memory) 최근 120일 → 본문
 2. SemiAnalysis 공개 피드 (semianalysis.com/feed) 중 메모리 관련 글 → 본문 발췌
 3. 기사 캐시 data/memory_news.json (한 번 읽은 글은 다시 안 읽음)
 4. Claude: 분기별·세그먼트별 계약가 전망 표(JSON) + 한국어 리서치 요약(markdown)

실행: python scripts/memory_outlook.py [--days 120] [--dry-run]
환경변수: ANTHROPIC_API_KEY
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from common import DATA, KST, ROOT, clean_markdown, load_json, now_iso

OUT = DATA / "memory_outlook.json"
CACHE = DATA / "memory_news.json"
PROMPT = ROOT / "prompts" / "memory_outlook.md"
MODEL = os.environ.get("REPORT_MODEL", "claude-sonnet-5-5")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
KW = re.compile(r"DRAM|NAND|HBM|memory|SSD|DDR|flash|Micron|SK hynix|Samsung", re.I)


def html_text(html: str) -> str:
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<nav.*?</nav>|<footer.*?</footer>", " ", html, flags=re.S)
    body = re.sub(r"</(p|div|h\d|li|tr|br)>", "\n", body)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"&nbsp;|&#160;", " ", body); body = re.sub(r"&amp;", "&", body)
    body = re.sub(r"[ \t]+", " ", body); body = re.sub(r"\n\s*\n+", "\n", body)
    return body.strip()


def article_core(text: str) -> str:
    """TrendForce 기사 본문: 'Press Center' 머리와 'Related Articles' 꼬리를 잘라낸다."""
    i = text.find("Home Press Center"); i = text.find("\n", i) if i > 0 else 0
    for end in ("Previous Article", "Related Articles", "Next Article", "Recommended"):
        j = text.find(end, i + 500)
        if j > 0:
            text = text[:j]
    return text[i:].strip()


def trendforce_links(days: int) -> list[tuple[str, str, str]]:
    """(url, date, title) — 보도자료 목록 페이지(5건/페이지)를 기간이 찰 때까지 넘긴다."""
    links = {}
    for page in range(1, 40):
        url = f"https://www.trendforce.com/presscenter/news?page={page}"
        try:
            t = requests.get(url, headers=UA, timeout=30).text
        except Exception as e:
            print(f"  {url}: {e}", file=sys.stderr); break
        found = re.findall(r"<a[^>]+href=\"((?:https?://www\.trendforce\.com)?/presscenter/news/(\d{8})-\d+\.html)\"[^>]*>(.*?)</a>", t, re.S)
        if not found:
            break
        oldest = None
        for href, d, inner in found:
            u = href if href.startswith("http") else "https://www.trendforce.com" + href
            day = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
            if title and (u not in links or len(title) > len(links[u][1])):
                links[u] = (day, title)
            elif u not in links:
                links[u] = (day, "")
            oldest = min(oldest or day, day)
        if oldest and (date.today() - date.fromisoformat(oldest)).days > days:
            break
    rows = [(u, d, ti) for u, (d, ti) in links.items() if (date.today() - date.fromisoformat(d)).days <= days]
    print(f"  trendforce press links: {len(rows)}")
    return sorted(rows, key=lambda x: x[1], reverse=True)


def fetch_trendforce(cache: dict, days: int):
    for u, day, title in trendforce_links(days):
        if u in cache:
            if title and cache[u].get("title") in ("", "Press Center"):
                cache[u]["title"] = title
            continue
        try:
            html = requests.get(u, headers=UA, timeout=30).text
        except Exception as e:
            print(f"  {u}: {e}", file=sys.stderr); continue
        text = article_core(html_text(html))[:9000]
        if not title:
            title = text.split("\n", 1)[0][:160]
        if not KW.search(title + text[:600]):
            continue
        cache[u] = {"source": "TrendForce", "date": day, "title": title, "text": text}
        print(f"  TF {day} {title[:70]}")


def fetch_semianalysis(cache: dict, days: int):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    for feed in ("https://www.semianalysis.com/feed", "https://newsletter.semianalysis.com/feed"):
        try:
            r = requests.get(feed, headers=UA, timeout=60); root = ET.fromstring(r.content)
        except Exception as e:
            print(f"  {feed}: {e}", file=sys.stderr); continue
        for it in root.findall(".//item"):
            link = (it.findtext("link") or "").strip(); title = (it.findtext("title") or "").strip()
            pub = it.findtext("pubDate") or ""
            try:
                ts = parsedate_to_datetime(pub)
            except Exception:
                continue
            if ts < since or link in cache:
                continue
            content = it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or it.findtext("description") or ""
            text = html_text(content)
            # 메모리 관련 문단만 모은다
            paras = [p for p in text.split("\n") if KW.search(p)]
            if not (KW.search(title) or len(paras) >= 6):
                continue
            cache[link] = {"source": "SemiAnalysis", "date": ts.date().isoformat(), "title": title, "text": ("\n".join(paras) if not KW.search(title) else text)[:9000]}
            print(f"  SA {ts.date()} {title[:70]}")


def call_claude(system: str, user: str) -> tuple[str, dict]:
    from anthropic import Anthropic
    client = Anthropic()
    messages = [{"role": "user", "content": user}]
    body, meta = "", {"stop": "", "in": 0, "out": 0}
    for _ in range(3):
        with client.messages.stream(model=MODEL, max_tokens=16000, system=system, messages=messages) as stream:
            for _ in stream.text_stream:
                pass
            resp = stream.get_final_message()
        chunk = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        body += chunk; meta["stop"] = resp.stop_reason; meta["in"] += resp.usage.input_tokens; meta["out"] += resp.usage.output_tokens
        if resp.stop_reason != "max_tokens":
            break
        messages += [{"role": "assistant", "content": chunk}, {"role": "user", "content": "이어서 끝까지."}]
    return body, meta


def parse_json(txt: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip(), flags=re.M)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    s = re.sub(r",\s*([}\]])", r"\1", m.group(0))
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cache = load_json(CACHE, {})
    fetch_trendforce(cache, args.days)
    fetch_semianalysis(cache, args.days)
    cutoff = (date.today() - timedelta(days=400)).isoformat()
    cache = {k: v for k, v in cache.items() if v.get("date", "") >= cutoff}
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    recent = sorted([v | {"url": k} for k, v in cache.items() if v["date"] >= (date.today() - timedelta(days=args.days)).isoformat()], key=lambda x: x["date"], reverse=True)
    print(f"articles in window: {len(recent)}")
    if not recent:
        return 0
    prices = load_json(DATA / "memory_prices.json", {})
    latest = []
    for name, it in prices.get("items", {}).items():
        h = it.get("history") or []
        if h:
            latest.append(f"- {it['label']} · {name}: {h[-1][1]} USD ({h[-1][0]}, 전일/전세션 {h[-1][2]}%)")
    user = "\n\n".join([
        f"# 작성 기준일 {date.today()} (KST)",
        "## 현재 현물·계약가 (TrendForce 공개 페이지, 사이트 수집)\n" + ("\n".join(latest) or "미수집"),
        "## 기사·보도자료 (최신순)\n" + "\n\n".join(f"=== [{a['source']}] {a['date']} {a['title']}\nURL: {a['url']}\n{a['text'][:7000]}" for a in recent[:40]),
        "위 자료만 근거로 스킬 지침대로 JSON, 구분선, 요약 markdown 순으로 출력하라.",
    ])
    print(f"user message: {len(user):,} chars")
    if args.dry_run:
        print(user[:3000]); return 0
    body, meta = call_claude(PROMPT.read_text(encoding="utf-8"), user)
    print(f"stop={meta['stop']} in={meta['in']} out={meta['out']}")
    head, _, summary = body.partition("-----SUMMARY-----")
    j = parse_json(head)
    if not j or "forecasts" not in j:
        print("JSON parse failed", file=sys.stderr); print(head[:2000]); return 1
    j["summary_md"] = clean_markdown(summary.strip() or j.get("summary_md", ""))
    j["updatedAt"] = now_iso(); j["model"] = MODEL
    j["sources"] = [{"source": a["source"], "date": a["date"], "title": a["title"], "url": a["url"]} for a in recent[:40]]
    OUT.write_text(json.dumps(j, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"saved: {len(j['forecasts'])} forecasts, {len(j.get('hbm', []))} hbm points")
    return 0


if __name__ == "__main__":
    sys.exit(main())
