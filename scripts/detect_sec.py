"""미국 관심종목의 SEC EDGAR 실적 공시를 감지해 리포트를 자동 생성한다.

 1. company_tickers.json 으로 티커 → CIK
 2. data.sec.gov/submissions/CIK##########.json 의 최근 공시에서 8-K(실적 보도자료 EX-99.1), 10-Q, 10-K 추출
 3. 미처리 공시 → 본문(HTML→텍스트) + Yahoo 분기 재무 맥락 → generate_report.py (--kind) 로 리포트
 4. data/filings_sec.json 에 이력. 같은 분기에 10-Q(상세)가 나중에 오면 갱신

실행: python scripts/detect_sec.py [--days 14] [--dry-run]
환경변수: ANTHROPIC_API_KEY. SEC는 User-Agent에 연락처를 요구한다 (SEC_USER_AGENT 로 덮어쓸 수 있음).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from common import DATA, ROOT, load_json, now_iso

STATE = DATA / "filings_sec.json"
UA = os.environ.get("SEC_USER_AGENT", "AKME Research stock site (akmeresearch@users.noreply.github.com)")
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
# (form, 종류, 상세도) — 8-K 보도자료가 먼저 오고(level 1) 10-Q/10-K 가 나중에(level 2)
FORMS = {"8-K": ("8-K 실적 보도자료", 1), "10-Q": ("10-Q 분기보고서", 2), "10-K": ("10-K 연차보고서", 2)}


def sec_get(url: str, timeout: int = 30):
    """SEC는 데이터센터 IP + 선언형 UA 요청을 403으로 막는다. 브라우저 TLS 지문(curl_cffi chrome)으로 요청하고, 안 되면 기본 방식으로 재시도."""
    try:
        from curl_cffi import requests as cffi
        r = cffi.get(url, impersonate="chrome", timeout=timeout, headers={"Accept": "application/json,text/html,*/*", "Accept-Language": "en-US,en;q=0.9"})
        if r.status_code == 200:
            return r
        print(f"  sec {r.status_code} via chrome impersonation: {url[:80]}", file=sys.stderr)
    except ImportError:
        pass
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r


def cik_map() -> dict[str, str]:
    j = sec_get("https://www.sec.gov/files/company_tickers.json").json()
    return {v["ticker"].upper(): f"{int(v['cik_str']):010d}" for v in j.values()}


def recent_filings(cik: str, days: int) -> list[dict]:
    j = sec_get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
    rc = j.get("filings", {}).get("recent", {})
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for i, form in enumerate(rc.get("form", [])):
        if form not in FORMS or rc["filingDate"][i] < cutoff:
            continue
        out.append({"form": form, "filingDate": rc["filingDate"][i], "reportDate": rc.get("reportDate", [None] * len(rc["form"]))[i],
                    "accession": rc["accessionNumber"][i], "primary": rc["primaryDocument"][i], "items": rc.get("items", [""] * len(rc["form"]))[i]})
    return out


def html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    text = soup.get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t\xa0]+", " ", text)).strip()


def filing_text(cik: str, f: dict) -> tuple[str, str] | None:
    """(라벨, 본문). 8-K는 Item 2.02 실적 보도자료(EX-99.1)만, 10-Q/10-K는 본문."""
    acc = f["accession"].replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}"
    if f["form"] == "8-K":
        if "2.02" not in (f.get("items") or ""):
            return None  # 실적 발표가 아닌 8-K
        idx = sec_get(f"{base}/index.json").json()
        names = [it["name"] for it in idx.get("directory", {}).get("item", [])]
        ex = [n for n in names if re.search(r"ex[-_]?99", n, re.I) and n.lower().endswith((".htm", ".html"))]
        if not ex:
            return None
        texts = [html_to_text(sec_get(f"{base}/{n}").text) for n in ex[:2]]
        return (f"8-K EX-99 {f['filingDate']}", "\n\n=====\n\n".join(texts))
    html = sec_get(f"{base}/{f['primary']}", timeout=60).text
    return (f"{f['form']} {f['filingDate']}", trim_10q(html_to_text(html)))


KEYS_10Q = ("RESULTS OF OPERATIONS", "Results of Operations", "MANAGEMENT'S DISCUSSION", "Management's Discussion", "Outlook", "OUTLOOK",
            "Segment Information", "SEGMENT INFORMATION", "Revenue by", "Guidance", "Liquidity and Capital Resources")


def trim_10q(text: str, limit: int = 150_000) -> str:
    """10-Q/10-K 처럼 긴 문서는 MD&A·실적 설명 구간을 우선 남긴다."""
    if len(text) <= limit:
        return text
    head = text[:15_000]
    pos = sorted({m.start() for k in KEYS_10Q for m in re.finditer(re.escape(k), text)})
    chunks, last, used = [], -1, 0
    per = max(20_000, (limit - len(head)) // 5)
    for i in pos:
        if i < last:
            continue
        c = text[i:i + per]; chunks.append(c); used += len(c); last = i + per
        if used >= limit - len(head):
            break
    body = "\n\n[...]\n\n".join(chunks) if chunks else text[15_000:limit]
    return (head + "\n\n[...]\n\n" + body)[:limit]


def period_of(f: dict) -> str:
    """실적 분기 라벨: 공시일 25일 전이 속한 달력 분기 (회계분기 종료월 기준과 맞춤)."""
    d = datetime.strptime(f["filingDate"], "%Y-%m-%d").date() - timedelta(days=25)
    if f["form"] in ("10-Q", "10-K") and f.get("reportDate"):
        d = datetime.strptime(f["reportDate"], "%Y-%m-%d").date()
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def fin_context(ticker: str) -> str:
    d = load_json(DATA / "financials" / f"{ticker}.json", {})
    q = d.get("quarters", {})
    if not q:
        return "직전 분기 재무: 미제공"
    lines = ["직전 분기 재무 (Yahoo Finance 분기 손익계산서, 단위 백만 USD; 분기 라벨은 회계분기 종료월의 달력 분기)",
             "| 분기 | 회계분기 종료일 | 매출액 | 영업이익 | 순이익 | 영업이익률 |", "| --- | --- | --- | --- | --- | --- |"]
    for k in sorted(q)[-6:]:
        r = q[k]; s, o, n = (r.get(x, {}).get("q") for x in ("매출액", "영업이익", "당기순이익"))
        m = lambda v: "—" if v is None else f"{v / 1e6:,.0f}"
        opm = f"{o / s * 100:.1f}%" if s and o is not None else "—"
        lines.append(f"| {k} | {r.get('period_end', '')} | {m(s)} | {m(o)} | {m(n)} | {opm} |")
    return "\n".join(lines)


def generate(ticker: str, period: str, label: str, text: str, kind: str, price_note: str) -> bool:
    tmp = Path("/tmp") / f"sec_{ticker}_{period}.txt"
    tmp.write_text(f"=== {label} ===\n{text}", encoding="utf-8")
    ctx = Path("/tmp") / f"ctx_{ticker}_{period}.txt"
    ctx.write_text(fin_context(ticker), encoding="utf-8")
    cmd = [sys.executable, str(ROOT / "scripts" / "generate_report.py"), "--ticker", ticker, "--period", period,
           "--source", str(tmp), "--source", str(ctx), "--kind", kind, "--price", price_note]
    print("  run:", " ".join(cmd[2:]))
    return subprocess.call(cmd) == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    wl = json.loads((DATA / "watchlist.json").read_text(encoding="utf-8"))
    us = wl.get("us", [])
    if not us:
        return 0
    state = load_json(STATE, {"seen": {}, "reports": {}})
    try:
        ciks = cik_map()
    except Exception as e:
        print(f"cik map FAIL {e}", file=sys.stderr); return 1
    generated = failed = 0
    for s in us:
        t = s["ticker"].upper(); cik = ciks.get(t)
        if not cik:
            print(f"{t}: CIK not found", file=sys.stderr); continue
        s["cik"] = cik
        try:
            filings = recent_filings(cik, args.days)
        except Exception as e:
            print(f"{t}: submissions FAIL {e}", file=sys.stderr); continue
        print(f"{t} (CIK {cik}): {len(filings)} candidate filings in {args.days}d")
        for f in sorted(filings, key=lambda x: x["filingDate"]):
            acc = f["accession"]
            if acc in state["seen"]:
                continue
            kind, level = FORMS[f["form"]]
            period = period_of(f)
            key = f"{t}_{period}"
            state["seen"][acc] = {"ticker": t, "form": f["form"], "filingDate": f["filingDate"], "period": period}
            done = state["reports"].get(key, {})
            if done and done.get("level", 0) >= level:
                print(f"  skip {f['form']} {f['filingDate']} — {key} has level {done.get('level')}"); continue
            try:
                got = filing_text(cik, f)
            except Exception as e:
                print(f"  {f['form']} {acc} fetch FAIL {e}", file=sys.stderr); state["seen"].pop(acc, None); continue
            if not got:
                print(f"  skip {f['form']} {f['filingDate']} (실적 항목 아님)"); continue
            label, text = got
            print(f"  NEW {f['form']} {f['filingDate']} → {key} ({len(text):,} chars)")
            if args.dry_run:
                continue
            p = load_json(DATA / "prices" / f"{t}.json", {})
            price_note = f"{p.get('price')} USD / 시총 {p.get('marketCap')} / PER {p.get('per')} ({p.get('quoteAt', '')[:10]})" if p.get("price") else "미제공"
            if generate(t, period, label, text, kind, price_note):
                state["reports"][key] = {"accession": acc, "form": f["form"], "level": level, "at": now_iso()}
                generated += 1
            else:
                failed += 1; state["seen"].pop(acc, None)
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    state["updatedAt"] = now_iso()
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # CIK 를 watchlist 에 저장
    (DATA / "watchlist.json").write_text(json.dumps(wl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\ngenerated {generated}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
