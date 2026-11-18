"""데일리 시장 브리핑 → data/daily/{YYYY-MM-DD}-{us|kr}.md + index.json

 --mode us : 전일 미국장 요약 (KST 07:00 실행). 미국 지수·섹터 ETF·대형주·금리·달러·원자재·공포탐욕·야간 코스피선물 + 미국 뉴스 헤드라인
 --mode kr : 당일 한국장 요약 (KST 20:00 실행). 코스피·코스닥·투자자별 수급·환율·예탁금/신용·관심종목·업종·상승/하락 상위 + 국내 뉴스 헤드라인

실행: python scripts/daily_brief.py --mode us|kr [--date 2026-11-18] [--dry-run] [--force]
환경변수: ANTHROPIC_API_KEY (필수), DART_API_KEY (kr 모드 공시, 선택)
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

from common import DATA, KST, ROOT, clean_markdown, get_json, load_json, now_iso

OUT = DATA / "daily"
PROMPT = ROOT / "prompts" / "daily_brief.md"
MODEL = os.environ.get("REPORT_MODEL", "claude-sonnet-5-5")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

US_SYMBOLS = [  # (심볼, 이름, 그룹)
    ("^GSPC", "S&P 500", "지수"), ("^IXIC", "나스닥", "지수"), ("^DJI", "다우", "지수"), ("^RUT", "러셀2000", "지수"), ("^SOX", "필라델피아 반도체", "지수"),
    ("^VIX", "VIX", "지표"), ("^TNX", "미 10년물(%)", "지표"), ("^IRX", "미 3개월물(%)", "지표"), ("DX-Y.NYB", "달러지수", "지표"),
    ("CL=F", "WTI", "원자재"), ("GC=F", "금", "원자재"), ("HG=F", "구리", "원자재"), ("BTC-USD", "비트코인", "원자재"), ("KRW=X", "원/달러", "지표"),
    ("XLK", "기술", "섹터ETF"), ("SMH", "반도체", "섹터ETF"), ("XLC", "커뮤니케이션", "섹터ETF"), ("XLY", "경기소비재", "섹터ETF"), ("XLP", "필수소비재", "섹터ETF"),
    ("XLF", "금융", "섹터ETF"), ("XLV", "헬스케어", "섹터ETF"), ("XLI", "산업재", "섹터ETF"), ("XLE", "에너지", "섹터ETF"), ("XLU", "유틸리티", "섹터ETF"),
    ("XLB", "소재", "섹터ETF"), ("XLRE", "부동산", "섹터ETF"), ("EWY", "MSCI 한국 ETF", "섹터ETF"),
    ("NVDA", "NVIDIA", "대형주"), ("AAPL", "Apple", "대형주"), ("MSFT", "Microsoft", "대형주"), ("GOOGL", "Alphabet", "대형주"), ("AMZN", "Amazon", "대형주"),
    ("META", "Meta", "대형주"), ("TSLA", "Tesla", "대형주"), ("AVGO", "Broadcom", "대형주"), ("TSM", "TSMC ADR", "대형주"), ("ASML", "ASML", "대형주"),
    ("MU", "Micron", "대형주"), ("AMD", "AMD", "대형주"), ("INTC", "Intel", "대형주"), ("ORCL", "Oracle", "대형주"), ("BE", "Bloom Energy", "대형주"),
]
US_FEEDS = [
    ("CNBC Markets", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC Finance", "https://www.cnbc.com/id/15839135/device/rss/rss.html"),
    ("CNBC Economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("WSJ Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Investing.com", "https://www.investing.com/rss/news_25.rss"),
]
KR_FEEDS = [
    ("연합뉴스 경제", "https://www.yna.co.kr/rss/economy.xml"),
    ("한국경제 증권", "https://www.hankyung.com/feed/finance"),
    ("매일경제 증권", "https://www.mk.co.kr/rss/50200011/"),
    ("매일경제 경제", "https://www.mk.co.kr/rss/30100041/"),
    ("연합인포맥스", "https://news.einfomax.co.kr/rss/allArticle.xml"),
]


def f(n, d=2):
    return "—" if n is None else f"{n:+.{d}f}%"


def fmtn(n, d=2):
    return "—" if n is None else f"{n:,.{d}f}"


# ---------------------------------------------------------------- 뉴스
def rss(name: str, url: str, since: datetime, limit: int = 25) -> list[str]:
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  rss {name}: {e}", file=sys.stderr)
        return []
    out = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item") or root.findall(".//atom:entry", ns)
    for it in items:
        title = (it.findtext("title") or it.findtext("atom:title", default="", namespaces=ns) or "").strip()
        pub = it.findtext("pubDate") or it.findtext("atom:updated", default="", namespaces=ns) or it.findtext("atom:published", default="", namespaces=ns) or ""
        ts = None
        try:
            ts = parsedate_to_datetime(pub) if pub and not pub[:4].isdigit() else (datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else None)
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            ts = None
        if ts and ts < since:
            continue
        desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or it.findtext("atom:summary", default="", namespaces=ns) or "")
        desc = re.sub(r"\s+", " ", desc).strip()[:160]
        if title:
            stamp = ts.astimezone(KST).strftime("%m-%d %H:%M") if ts else ""
            out.append(f"- [{name} {stamp}] {title}" + (f" — {desc}" if desc and desc[:30] not in title else ""))
        if len(out) >= limit:
            break
    print(f"  rss {name}: {len(out)}")
    return out


def news_block(feeds, hours: int, cap: int = 60) -> str:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    lines = []
    for name, url in feeds:
        lines += rss(name, url, since)
    # 제목 중복 제거
    seen, uniq = set(), []
    for ln in lines:
        key = re.sub(r"\W+", "", ln.split("] ", 1)[-1][:40]).lower()
        if key in seen:
            continue
        seen.add(key); uniq.append(ln)
    return "\n".join(uniq[:cap]) if uniq else "- (뉴스 수집 실패)"


# ---------------------------------------------------------------- 미국장
def us_quotes() -> tuple[dict, str | None]:
    """{sym: {name, group, close, prev, chg, chg5d, date}} 와 최근 거래일."""
    import yfinance as yf
    syms = [s for s, _, _ in US_SYMBOLS]
    df = yf.download(syms, period="10d", interval="1d", auto_adjust=False, progress=False, threads=True)
    close = df["Close"] if "Close" in df else df
    out, last = {}, None
    for sym, name, group in US_SYMBOLS:
        try:
            s = close[sym].dropna()
        except Exception:
            continue
        if len(s) < 2:
            continue
        d = s.index[-1].date().isoformat()
        c, p = float(s.iloc[-1]), float(s.iloc[-2])
        c5 = float(s.iloc[-6]) if len(s) >= 6 else None
        out[sym] = {"name": name, "group": group, "close": c, "prev": p, "chg": (c / p - 1) * 100 if p else None,
                    "chg5d": (c / c5 - 1) * 100 if c5 else None, "date": d}
        if sym == "^GSPC":
            last = d
    return out, last


def us_pack(today: date) -> tuple[str, str | None]:
    q, last = us_quotes()
    lines = [f"기준: {last} 미국 정규장 종가 (작성 {now_iso()}, KST {today})", ""]
    for group in ("지수", "지표", "원자재", "섹터ETF", "대형주"):
        lines.append(f"## {group}")
        lines.append("| 이름 | 종가 | 전일 대비 | 5거래일 | 기준일 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for sym, name, g in US_SYMBOLS:
            if g != group or sym not in q:
                continue
            r = q[sym]
            lines.append(f"| {name} ({sym}) | {fmtn(r['close'])} | {f(r['chg'])} | {f(r['chg5d'])} | {r['date']} |")
        lines.append("")
    # 심리·야간선물·GDR
    sent = {it["id"]: it for it in load_json(DATA / "sentiment.json", {}).get("items", [])}
    fg = sent.get("fear-greed", {})
    lines.append("## 심리")
    lines.append(f"- CNN 공포·탐욕 지수: {fmtn(fg.get('value'), 0)} ({fg.get('asOf', '')}), 1주 전 {fmtn((fg.get('comparisons') or {}).get('1w'), 0)}, 1달 전 {fmtn((fg.get('comparisons') or {}).get('1m'), 0)}")
    pc = sent.get("put-call", {}); lines.append(f"- Put/Call: {fmtn(pc.get('value'))} ({pc.get('asOf', '')})")
    yc = sent.get("yield-curve", {}); lines.append(f"- 미 10년-2년 금리차: {fmtn(yc.get('value'))}%p ({yc.get('asOf', '')})")
    lines.append("")
    ov = load_json(DATA / "overseas.json", {})
    nf = (ov.get("nightFutures") or {}).get("night") or {}
    lines.append("## 한국 관련 (미국장 중 거래)")
    if nf.get("price"):
        lines.append(f"- 야간 코스피200 선물: {fmtn(nf['price'])} ({f(nf.get('changePercent'))}, 전일 주간 종가 대비 {ov.get('nightFutures', {}).get('nightVsDayPct')}%) — 수집 {ov.get('nightFutures', {}).get('collectedAt', '')}")
    for d in ov.get("depositary", []):
        if d.get("status") == "ok":
            lines.append(f"- {d['name']} ({d.get('venue', '')}): {fmtn(d.get('price'))} ({f(d.get('changePercent'))}, {d.get('asOf', '')})")
    lines.append(f"- 원/달러 (사이트 수집): {ov.get('usdkrw')}")
    lines.append("")
    lines.append("## 미국 뉴스 헤드라인 (최근 24시간, 수집 순)")
    lines.append(news_block(US_FEEDS, 24))
    lines.append("")
    return "\n".join(lines), last


# ---------------------------------------------------------------- 한국장
def naver_json(url: str):
    try:
        return requests.get(url, headers={**UA, "Referer": "https://m.stock.naver.com/"}, timeout=20).json()
    except Exception as e:
        print(f"  naver {url[:60]}: {e}", file=sys.stderr)
        return None


def kr_movers() -> list[str]:
    lines = []
    for mk in ("KOSPI", "KOSDAQ"):
        for kind, label in (("up", "상승"), ("down", "하락")):
            j = naver_json(f"https://m.stock.naver.com/api/stocks/{kind}/{mk}?page=1&pageSize=8")
            rows = (j or {}).get("stocks") or []
            if rows:
                lines.append(f"- {mk} {label} 상위: " + ", ".join(
                    f"{r.get('stockName')} {r.get('fluctuationsRatio', '')}%" for r in rows[:8]))
    # 업종 등락 (네이버 업종 그룹, 등락률·상승/하락 종목 수)
    j = naver_json("https://m.stock.naver.com/api/stocks/industry?page=1&pageSize=100")
    groups = (j or {}).get("groups") or []
    rows = []
    for g in groups:
        try:
            rows.append((g.get("name"), float(str(g.get("changeRate", "")).replace("%", "")), g.get("riseCount"), g.get("fallCount"), g.get("totalCount")))
        except ValueError:
            pass
    if rows:
        rows.sort(key=lambda x: x[1], reverse=True)
        fmt = lambda r: f"{r[0]} {r[1]:+.2f}% (상승 {r[2]}/하락 {r[3]}/전체 {r[4]})"
        lines.append("- 업종 상승 상위: " + ", ".join(fmt(r) for r in rows[:10]))
        lines.append("- 업종 하락 상위: " + ", ".join(fmt(r) for r in rows[-10:][::-1]))
        up = sum(1 for r in rows if r[1] > 0); lines.append(f"- 업종 {len(rows)}개 중 상승 {up}, 하락 {len(rows) - up}")
    return lines


def kr_pack(today: date) -> tuple[str, str | None]:
    mk = load_json(DATA / "market.json", {}).get("markets", {})
    ks, kq = mk.get("KOSPI", {}), mk.get("KOSDAQ", {})
    last = ks.get("date")
    lines = [f"기준: {last} 한국 정규장 (작성 {now_iso()})", ""]
    lines.append("## 지수·투자자별 순매수 (억원, 장 마감 누적)")
    lines.append("| 시장 | 종가 | 등락 | 외국인 | 개인 | 기관 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for m in (ks, kq):
        p = (m.get("points") or [{}])[-1]
        lines.append(f"| {m.get('name', '')} | {fmtn(m.get('price'))} | {f(m.get('changePercent'))} | {fmtn(p.get('foreignNet'), 0)} | {fmtn(p.get('indivNet'), 0)} | {fmtn(p.get('instNet'), 0)} |")
    fd = load_json(DATA / "flows_daily.json", {}).get("rows", {})
    recent = sorted(fd)[-5:]
    lines.append("")
    lines.append("## 외국인 일별 순매수 최근 5일 (억원; FUT=코스피200 선물)")
    for d in recent:
        r = fd[d]
        lines.append(f"- {d}: 코스피 {fmtn(r.get('KOSPI'), 0)} (종가 {fmtn(r.get('KOSPI_close'))}), 코스닥 {fmtn(r.get('KOSDAQ'), 0)}, 선물 {fmtn(r.get('FUT'), 0)}")
    lines.append("")
    ind = {it["id"]: it for it in load_json(DATA / "indicators.json", {}).get("items", [])}
    lines.append("## 환율·금리·해외 (사이트 수집 시점 기준)")
    for k in ("usdkrw", "us10y", "nasdaq", "sp500", "vix", "wti", "gold"):
        it = ind.get(k, {})
        lines.append(f"- {it.get('name', k)}: {fmtn(it.get('price'))} ({f(it.get('changePercent'))}, {str(it.get('quoteAt', ''))[:16]})")
    ov = load_json(DATA / "overseas.json", {})
    nf = ov.get("nightFutures") or {}
    if (nf.get("day") or {}).get("price"):
        lines.append(f"- 코스피200 선물 주간 종가 {fmtn(nf['day']['price'])} ({f(nf['day'].get('changePercent'))}), 야간 {fmtn((nf.get('night') or {}).get('price'))} ({f((nf.get('night') or {}).get('changePercent'))}) 수집 {nf.get('collectedAt', '')}")
    lines.append("")
    cr = load_json(DATA / "credit.json", {})
    pts = cr.get("points") or []
    if pts:
        r, r1, r5 = pts[-1], (pts[-2] if len(pts) > 1 else {}), (pts[-6] if len(pts) > 5 else {})
        lines.append(f"## 고객예탁금·신용잔고 (억원, {r.get('date')} 기준 — 2영업일 지연 자료)")
        lines.append(f"- 예탁금 {fmtn(r.get('deposit'), 0)} (전일 대비 {fmtn((r.get('deposit') or 0) - (r1.get('deposit') or 0), 0):>}, 5일 전 대비 {fmtn((r.get('deposit') or 0) - (r5.get('deposit') or 0), 0)})")
        lines.append(f"- 신용잔고 {fmtn(r.get('credit'), 0)} (전일 대비 {fmtn((r.get('credit') or 0) - (r1.get('credit') or 0), 0)}, 5일 전 대비 {fmtn((r.get('credit') or 0) - (r5.get('credit') or 0), 0)})")
        lines.append("")
    wl = load_json(DATA / "watchlist.json", {})
    lines.append("## 관심종목 당일")
    lines.append("| 종목 | 종가 | 등락 | 거래대금 | 52주 고/저 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for s in wl.get("kr", []):
        p = load_json(DATA / "prices" / f"{s['ticker']}.json", {})
        inf = p.get("infos", {})
        lines.append(f"| {s['name']} | {fmtn(p.get('price'), 0)} | {f(p.get('changePercent'))} | {inf.get('대금', '—')} | {p.get('high52', '—')}/{p.get('low52', '—')} |")
    lines.append("")
    lines.append("## 상승·하락 상위, 업종")
    mv = kr_movers()
    lines += mv or ["- (수집 실패)"]
    lines.append("")
    # 오늘 리포트·공시
    idx = load_json(DATA / "reports" / "index.json", [])
    todays = [r for r in idx if r.get("published", "") == today.isoformat()]
    lines.append("## 오늘 발행 실적 리포트")
    lines += [f"- {r['name']} {r['period']}: {r['summary']}" for r in todays] or ["- 없음"]
    lines.append("")
    key = os.environ.get("DART_API_KEY", "")
    lines.append("## 오늘 관심종목 DART 공시")
    got = 0
    if key:
        for s in wl.get("kr", []):
            if not s.get("dart_corp_code"):
                continue
            try:
                payload = get_json("https://opendart.fss.or.kr/api/list.json", timeout=30, params={
                    "crtfc_key": key, "corp_code": s["dart_corp_code"], "bgn_de": today.strftime("%Y%m%d"), "end_de": today.strftime("%Y%m%d"), "page_count": 30})
                for it in payload.get("list", []) if payload.get("status") == "000" else []:
                    lines.append(f"- {s['name']}: {it.get('report_nm', '')}"); got += 1
            except Exception as e:
                print(f"  dart {s['name']}: {e}", file=sys.stderr)
    if not got:
        lines.append("- 없음 (또는 조회 불가)")
    lines.append("")
    lines.append("## 국내 뉴스 헤드라인 (최근 14시간, 수집 순)")
    lines.append(news_block(KR_FEEDS, 14))
    lines.append("")
    return "\n".join(lines), last


# ---------------------------------------------------------------- 공통
def call_claude(system: str, user: str) -> tuple[str, dict]:
    """출력이 max_tokens에 걸리면 이어서 요청 (thinking 토큰이 한도를 먹는 경우 대비)."""
    from anthropic import Anthropic
    client = Anthropic()
    messages = [{"role": "user", "content": user}]
    body, meta = "", {"stop": "", "in": 0, "out": 0}
    for _ in range(3):
        resp = client.messages.create(model=MODEL, max_tokens=16000, system=system, messages=messages)
        chunk = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        body += chunk
        meta["stop"] = resp.stop_reason; meta["in"] += resp.usage.input_tokens; meta["out"] += resp.usage.output_tokens
        print(f"stop_reason={resp.stop_reason} in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
        if resp.stop_reason != "max_tokens":
            break
        messages += [{"role": "assistant", "content": chunk},
                     {"role": "user", "content": "출력이 잘렸다. 마지막 문장 바로 다음부터 이어서, 반복 없이 끝까지 작성하라."}]
    return body, meta


def build_index():
    items = []
    for p in sorted(OUT.glob("*.md"), reverse=True):
        t = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", t, re.S)
        body = m.group(2) if m else t
        meta = dict(ln.split(":", 1) for ln in (m.group(1).splitlines() if m else []) if ":" in ln)
        title = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), p.stem)
        summary = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("> ")), "")
        items.append({"file": p.name, "date": meta.get("date", "").strip(), "kind": meta.get("kind", "").strip(),
                      "published": meta.get("published", "").strip(), "title": title, "summary": summary})
    items.sort(key=lambda x: (x["date"], x["published"]), reverse=True)
    (OUT / "index.json").write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"daily index: {len(items)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["us", "kr"])
    ap.add_argument("--date")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="휴장·중복 검사 무시")
    args = ap.parse_args()
    now = datetime.now(KST)
    mode = args.mode or ("us" if now.hour < 12 else "kr")
    today = date.fromisoformat(args.date) if args.date else now.date()
    pack, last = (us_pack if mode == "us" else kr_pack)(today)
    if args.dry_run:
        print(pack); return 0
    # 휴장 검사: us는 기준일이 어제(미국 날짜) 이어야, kr은 오늘이어야
    expect = (today - timedelta(days=1)).isoformat() if mode == "us" else today.isoformat()
    if not args.force and last != expect:
        print(f"skip: {mode} 기준일 {last} != {expect} (휴장 또는 데이터 미갱신)"); return 0
    out = OUT / f"{today}-{mode}.md"
    if out.exists() and not args.force:
        print(f"skip: {out.name} already exists"); return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr); return 1
    label = "전일 미국장" if mode == "us" else "오늘 한국장"
    user = pack + f"\n\n위 데이터 팩만 근거로 스킬 지침의 '{label}' 형식대로 데일리 브리핑을 작성하라. 제목의 날짜는 {today} (KST)."
    body, meta = call_claude(PROMPT.read_text(encoding="utf-8"), user)
    print(f"stop={meta['stop']} in={meta['in']} out={meta['out']}")
    OUT.mkdir(parents=True, exist_ok=True)
    front = ("---\n" f"date: {today}\nkind: {mode}\nbasis: {last}\npublished: {now.strftime('%Y-%m-%d %H:%M')}\nmodel: {MODEL}\n"
             f"tokens_in: {meta['in']}\ntokens_out: {meta['out']}\n---\n\n")
    out.write_text(front + clean_markdown(body.strip()) + "\n", encoding="utf-8")
    print(f"written: {out.relative_to(ROOT)}")
    build_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())
