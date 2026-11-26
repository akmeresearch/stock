"""딜 감시: 지정 기업의 인수·기술이전(라이선스)·공동개발·지분투자 뉴스를 감지해 텔레그램으로 알린다.

 소스: 구글뉴스 RSS (영문·한글 검색), SEC 8-K (Item 1.01 중요 계약 / 2.01 인수 완료) — 공개 소스만.
 흐름: 새 헤드라인 → 정규식 1차 필터 → Claude 가 딜 여부·유형·상대·금액 판정 → 같은 딜(상대방 기준) 1회만 알림
 설정: data/deal_watch.json   상태: data/deals.json (seen, alerts)

실행: python scripts/deal_watch.py [--days 3] [--dry-run]
환경변수: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN
"""
import argparse
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, KST, clean_markdown, load_json, now_iso, save_json  # noqa: E402

CONF = DATA / "deal_watch.json"
STATE = DATA / "deals.json"
MODEL = os.environ.get("REPORT_MODEL", "claude-sonnet-5-5")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
PRE = re.compile(r"acqui|buy|buys|bought|purchas|licens|collaborat|partner|deal|agreement|option|stake|merger|takeover|invest|alliance|"
                 r"인수|기술이전|기술 이전|라이선스|라이센스|계약|협력|파트너|도입|옵션|합병|투자|M&A|딜|손잡|체결", re.I)
TYPES = {"인수": "🏢", "기술이전·라이선스": "🧬", "공동개발·협력": "🤝", "지분투자": "💰", "기타": "📌"}


def parse_rss(content: bytes, default_src: str = "") -> list[dict]:
    root = ET.fromstring(content); out = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip(); link = (it.findtext("link") or "").strip()
        src = it.find("{https://news.google.com/rss}source"); src = src.text if src is not None else ""
        if not src and " - " in title:
            title, src = title.rsplit(" - ", 1)
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate") or "")
        except Exception:
            continue
        out.append({"title": title.strip(), "link": link, "source": (src or default_src).strip(), "ts": ts.astimezone(timezone.utc).isoformat()})
    return out


def fetch_rss(url: str, default_src: str = "", tries: int = 3) -> list[dict]:
    import time
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 200:
                return parse_rss(r.content, default_src)
            print(f"  rss {r.status_code}: {url[:70]}", file=sys.stderr)
        except Exception as e:
            print(f"  rss: {e}", file=sys.stderr)
        time.sleep(4 * (i + 1))
    return []


def google_news(query: str, lang: str) -> list[dict]:
    hl, gl, ceid = ("ko", "KR", "KR:ko") if lang == "ko" else ("en-US", "US", "US:en")
    got = fetch_rss(f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}")
    if got:
        return got
    # 구글이 막히면 빙 뉴스 RSS
    mkt = "ko-KR" if lang == "ko" else "en-US"
    return fetch_rss(f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss&setlang={mkt[:2]}&cc={mkt[-2:]}", "Bing News")


def yahoo_news(ticker: str) -> list[dict]:
    try:
        import yfinance as yf
        out = []
        for n in (yf.Ticker(ticker).news or [])[:40]:
            c = n.get("content") or n
            title = c.get("title") or ""; link = ((c.get("canonicalUrl") or {}).get("url")) or c.get("link") or ""
            pub = c.get("pubDate") or c.get("providerPublishTime")
            ts = datetime.fromisoformat(pub.replace("Z", "+00:00")) if isinstance(pub, str) else datetime.fromtimestamp(pub or 0, tz=timezone.utc)
            src = ((c.get("provider") or {}).get("displayName")) or n.get("publisher") or "Yahoo Finance"
            if title:
                out.append({"title": title, "link": link, "source": src, "ts": ts.astimezone(timezone.utc).isoformat()})
        return out
    except Exception as e:
        print(f"  yahoo {ticker}: {e}", file=sys.stderr); return []


def sec_8k(cik: str, days: int) -> list[dict]:
    """최근 8-K 중 Item 1.01 / 2.01 — 헤드라인 형태로 변환."""
    try:
        from curl_cffi import requests as cffi
        j = cffi.get(f"https://data.sec.gov/submissions/CIK{cik}.json", impersonate="chrome", timeout=30).json()
    except Exception as e:
        print(f"  sec {cik}: {e}", file=sys.stderr); return []
    rc = j.get("filings", {}).get("recent", {}); out = []
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    for i, form in enumerate(rc.get("form", [])):
        if form != "8-K" or rc["filingDate"][i] < cutoff:
            continue
        items = (rc.get("items") or [""] * len(rc["form"]))[i]
        if not re.search(r"\b(1\.01|2\.01)\b", items or ""):
            continue
        acc = rc["accessionNumber"][i].replace("-", "")
        link = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{rc['primaryDocument'][i]}"
        out.append({"title": f"SEC 8-K (Items {items}) filed {rc['filingDate'][i]}", "link": link, "source": "SEC EDGAR",
                    "ts": datetime.fromisoformat(rc["filingDate"][i]).replace(tzinfo=timezone.utc).isoformat()})
    return out


def norm_key(title: str) -> str:
    return hashlib.sha1(re.sub(r"\W+", "", title.lower())[:80].encode()).hexdigest()[:16]


def classify(company: dict, heads: list[dict]) -> list[dict]:
    from anthropic import Anthropic
    client = Anthropic()
    lines = "\n".join(f"{i + 1}. [{h['source']}] {h['title']}" for i, h in enumerate(heads))
    system = f"""너는 제약·바이오 딜 분석가다. 아래 뉴스 헤드라인이 {company['name']}({company.get('ko', '')})가 당사자인 **새로운 기업 인수, 기술이전(라이선스 인·아웃), 공동개발·협력 계약, 지분투자** 체결 소식인지 판정한다.
- 딜이 아닌 것: 실적·가이던스, 임상 결과, 승인, 가격 정책, 소송, 인사, 공장 투자(설비), 과거 딜의 재언급·분석 기사, 추측("논의 중" 보도는 is_deal=true 로 하되 status="보도·추측").
- 같은 딜을 다룬 여러 헤드라인은 같은 counterparty 로 묶는다. counterparty 는 영문 공식 표기(예: "LoQus23 Therapeutics").
JSON 배열만 출력: [{{"n": 1, "is_deal": true, "type": "인수|기술이전·라이선스|공동개발·협력|지분투자|기타", "counterparty": "...", "asset": "자산·모달리티·적응증 한 줄(한국어)", "value": "최대 7.25억달러 (없으면 null)", "status": "체결|완료|보도·추측", "summary": "한국어 한 문장", "kr_relevance": "한국 상장사 연관 있으면 한 줄, 없으면 null"}}]
is_deal 이 false 면 {{"n": k, "is_deal": false}} 만."""
    with client.messages.stream(model=MODEL, max_tokens=16000, system=system, messages=[{"role": "user", "content": lines}]) as stream:
        for _ in stream.text_stream:
            pass
        resp = stream.get_final_message()
    txt = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    print(f"  classify: {len(heads)} heads → {len(txt)} chars, stop={resp.stop_reason}"); print("  " + txt[:1200].replace("\n", " "))
    m = re.search(r"\[.*\]", re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M), re.S)
    try:
        arr = json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0))) if m else []
    except json.JSONDecodeError:
        print("  classify: JSON parse failed", file=sys.stderr); print(txt[:800]); return []
    out = []
    for a in arr:
        try:
            h = heads[int(a["n"]) - 1]
        except Exception:
            continue
        if a.get("is_deal"):
            out.append({**h, **{k: a.get(k) for k in ("type", "counterparty", "asset", "value", "status", "summary", "kr_relevance")}})
    return out


def tg(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    st = load_json(DATA / "notify.json", {})
    ids = [c["id"] if isinstance(c, dict) else c for c in st.get("chat_ids", [])] or ([st["chat_id"]] if st.get("chat_id") else [])
    if not token or not ids:
        print("  telegram not configured", file=sys.stderr); return False
    ok = False
    for cid in ids:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": cid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=30)
        ok = ok or r.ok
    return ok


def esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    conf = load_json(CONF, {"companies": []})
    state = load_json(STATE, {"seen": {}, "alerts": []})
    seen = state["seen"]
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    cutoff_seen = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff_seen}
    alerted_keys = {(a["company"], re.sub(r"\W+", "", (a.get("counterparty") or "").lower())) for a in state["alerts"] if a.get("at", "") >= cutoff_seen}
    sent = 0
    for c in conf["companies"]:
        heads = []
        for q in c.get("queries_en", []):
            heads += google_news(q, "en")
        for q in c.get("queries_ko", []):
            heads += google_news(q, "ko")
        if c.get("ticker"):
            heads += yahoo_news(c["ticker"])
        if c.get("cik"):
            heads += sec_8k(c["cik"], args.days)
        fresh, keys = [], set()
        for h in heads:
            k = norm_key(h["title"])
            if h["ts"] < since.isoformat() or k in seen or k in keys:
                continue
            if not (PRE.search(h["title"]) or h["source"] == "SEC EDGAR"):
                seen[k] = h["ts"]; continue
            keys.add(k); fresh.append(h)
        print(f"{c['name']}: {len(heads)} headlines, {len(fresh)} new candidates")
        if not fresh:
            continue
        if args.dry_run:
            for h in fresh:
                print("   ", h["ts"][:10], h["source"], "|", h["title"][:100])
            continue
        for h in fresh:
            print("   ", h["ts"][:10], h["source"], "|", h["title"][:90])
        deals = classify(c, fresh[:60]) if os.environ.get("ANTHROPIC_API_KEY") else []
        print(f"  deals: {len(deals)}")
        for h in fresh:
            seen[norm_key(h["title"])] = h["ts"]
        # 상대방 기준 묶기
        groups = {}
        for d in deals:
            ck = re.sub(r"\W+", "", (d.get("counterparty") or d["title"]).lower())
            groups.setdefault(ck, []).append(d)
        for ck, ds in groups.items():
            if (c["id"], ck) in alerted_keys:
                print(f"  already alerted: {ds[0].get('counterparty')}"); continue
            d = max(ds, key=lambda x: len(x.get("summary") or ""))
            icon = TYPES.get(d.get("type"), "📌")
            links = "\n".join(f"· <a href=\"{esc(x['link'])}\">{esc(x['source'] or '기사')}</a> {esc(x['title'][:80])}" for x in ds[:4])
            text = (f"{icon} <b>{esc(c.get('ko') or c['name'])} 딜 알림 — {esc(d.get('type'))}</b>\n"
                    f"<b>{esc(d.get('counterparty'))}</b>{(' · ' + esc(d['value'])) if d.get('value') else ''} · {esc(d.get('status'))}\n"
                    f"{esc(d.get('asset'))}\n\n{esc(d.get('summary'))}"
                    f"{('\n\n🇰🇷 ' + esc(d['kr_relevance'])) if d.get('kr_relevance') else ''}\n\n{links}")
            ok = tg(text); sent += ok
            state["alerts"].append({"company": c["id"], "at": now_iso(), "type": d.get("type"), "counterparty": d.get("counterparty"), "value": d.get("value"),
                                    "asset": d.get("asset"), "status": d.get("status"), "summary": d.get("summary"), "kr_relevance": d.get("kr_relevance"),
                                    "articles": [{"title": x["title"], "link": x["link"], "source": x["source"], "ts": x["ts"]} for x in ds[:6]], "sent": ok})
            print(f"  ALERT {d.get('type')} {d.get('counterparty')} {d.get('value')} sent={ok}")
    state["seen"] = seen
    state["alerts"] = state["alerts"][-300:]
    state["updatedAt"] = now_iso()
    if not args.dry_run:
        save_json(STATE, state)
    print(f"sent {sent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
