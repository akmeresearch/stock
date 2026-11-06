"""주간 시장 브리핑 생성 → data/weekly/{YYYY-MM-DD}.md (주의 금요일 날짜) + index.json

데이터 팩: data/ 의 indicators·sentiment·flows_daily·market·prices·reports·DART 공시 목록
실행: python scripts/weekly_brief.py [--end 2026-11-06] [--dry-run]
환경변수: ANTHROPIC_API_KEY (필수), DART_API_KEY (공시 목록, 선택)
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from common import DATA, KST, ROOT, get_json, load_json, now_iso

OUT = DATA / "weekly"
PROMPT = ROOT / "prompts" / "weekly_brief.md"
MODEL = os.environ.get("REPORT_MODEL", "claude-sonnet-5-5")


def pct(a, b):
    return None if not a or b is None or a == 0 else (b / a - 1) * 100


def f(n, d=1):
    """등락률 표기: +1.2% / —"""
    return "—" if n is None else f"{n:+.{d}f}%"


def fmtn(n, d=0):
    return "—" if n is None else f"{n:,.{d}f}"


def week_range(end: date) -> tuple[date, date]:
    """end 가 속한 주의 월~금. end 가 주말이면 직전 금요일 기준."""
    while end.weekday() > 4:
        end -= timedelta(days=1)
    start = end - timedelta(days=end.weekday())
    return start, end


def series_change(points: list[dict], start: date, end: date, key="close"):
    """주 시작 전 마지막 값 → 주 마지막 값."""
    pts = [p for p in points if p.get(key) is not None]
    before = [p for p in pts if p["date"] < start.isoformat()]
    during = [p for p in pts if start.isoformat() <= p["date"] <= end.isoformat()]
    if not before or not during:
        return None, None, None
    return before[-1][key], during[-1][key], pct(before[-1][key], during[-1][key])


def build_pack(start: date, end: date) -> str:
    lines = [f"기준 주간: {start} (월) ~ {end} (금)", f"데이터 수집 시각: {now_iso()}", ""]

    # 1. 지수·지표
    ind = load_json(DATA / "indicators.json", {})
    lines.append("## 지수·지표 주간 등락 (Yahoo 일봉 종가 기준)")
    lines.append("| 지표 | 주 시작 전 종가 | 주 마지막 종가 | 주간 등락 | 3개월 저~고 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for i in ind.get("items", []):
        a, b, c = series_change(i.get("points", []), start, end)
        d = i.get("digits", 2)
        lines.append(f"| {i['name']} | {fmtn(a, d)} | {fmtn(b, d)} | {f(c)} | {fmtn(i.get('low'), d)}~{fmtn(i.get('high'), d)} |")
    lines.append("")

    # 2. 외국인 수급 (일별)
    fl = load_json(DATA / "flows_daily.json", {}).get("rows", {})
    lines.append("## 외국인 일별 순매수 (억원, 장 마감 누적; 자료가 있는 날만)")
    lines.append("| 날짜 | 코스피 현물 | 코스닥 현물 | K200 선물 | 코스피 종가 |")
    lines.append("| --- | --- | --- | --- | --- |")
    n = 0
    for d_ in sorted(fl):
        if start.isoformat() <= d_ <= end.isoformat():
            r = fl[d_]
            lines.append(f"| {d_} | {fmtn(r.get('KOSPI'))} | {fmtn(r.get('KOSDAQ'))} | {fmtn(r.get('FUT'))} | {fmtn(r.get('KOSPI_close'), 2)} |")
            n += 1
    if n == 0:
        lines.append("| (이번 주 자료 없음) | | | | |")
    lines.append(f"(수급 자료 일수: {n}/5)")
    lines.append("")

    # 3. 심리
    sen = load_json(DATA / "sentiment.json", {})
    lines.append("## 시장 심리·보조지표")
    lines.append("| 지표 | 현재 | 기준일 | 1주 전 | 1개월 전 | 1년 전 | 등급 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for i in sen.get("items", []):
        if i.get("status") not in ("ok", "stale"):
            continue
        c = i.get("comparisons", {})
        d = i.get("digits", 2)
        lines.append(f"| {i.get('name')} | {fmtn(i.get('value'), d)} | {i.get('asOf')} | {fmtn(c.get('1w'), d)} | {fmtn(c.get('1m'), d)} | {fmtn(c.get('1y'), d)} | {i.get('rating') or ''} |")
    lines.append("")

    # 4. 관심종목
    wl = load_json(DATA / "watchlist.json", {})
    lines.append("## 관심종목 주간 등락")
    lines.append("| 종목 | 코드 | 섹터 | 주 시작 전 | 주 마지막 | 주간 | 52주 최고 | 52주 최저 | 현재가 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for s in wl.get("kr", []):
        p = load_json(DATA / "prices" / f"{s['ticker']}.json", {})
        a, b, c = series_change(p.get("points", []), start, end)
        lines.append(f"| {s['name']} | {s['ticker']} | {s.get('sector', '')} | {fmtn(a)} | {fmtn(b)} | {f(c)} | {p.get('high52') or '—'} | {p.get('low52') or '—'} | {fmtn(p.get('price'))} |")
    lines.append("")

    # 5. 이번 주 리포트
    idx = load_json(DATA / "reports" / "index.json", [])
    week_reports = [r for r in idx if start.isoformat() <= r.get("published", "") <= (end + timedelta(days=2)).isoformat()]
    lines.append("## 이번 주 발행 실적 리포트")
    if week_reports:
        for r in week_reports:
            lines.append(f"- {r['name']} {r['period']}: {r['summary']}")
    else:
        lines.append("- 없음")
    lines.append("")

    # 6. DART 주요 공시
    lines.append("## 이번 주 관심종목 DART 공시 (정기·주요사항·거래소 공시)")
    key = os.environ.get("DART_API_KEY", "")
    got = 0
    if key:
        for s in wl.get("kr", []):
            if not s.get("dart_corp_code"):
                continue
            try:
                payload = get_json("https://opendart.fss.or.kr/api/list.json", timeout=30, params={
                    "crtfc_key": key, "corp_code": s["dart_corp_code"],
                    "bgn_de": start.strftime("%Y%m%d"), "end_de": (end + timedelta(days=2)).strftime("%Y%m%d"), "page_count": 50})
                for it in payload.get("list", []) if payload.get("status") == "000" else []:
                    nm = it.get("report_nm", "")
                    if re.search(r"주요사항|잠정|분기보고서|반기보고서|사업보고서|공정공시|단일판매|유상증자|무상증자|자기주식|합병|분할|소송|임원ㆍ주요주주|최대주주", nm):
                        lines.append(f"- {it['rcept_dt']} {s['name']}: {nm}")
                        got += 1
            except Exception as e:
                print(f"dart list {s['name']}: {e}", file=sys.stderr)
    if got == 0:
        lines.append("- 없음 (또는 조회 불가)")
    lines.append("")
    return "\n".join(lines)


def call_claude(system: str, user: str) -> tuple[str, dict]:
    from anthropic import Anthropic
    client = Anthropic()
    resp = client.messages.create(model=MODEL, max_tokens=8000, system=system, messages=[{"role": "user", "content": user}])
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return text, {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens, "stop": resp.stop_reason}


def build_index():
    items = []
    for p in sorted(OUT.glob("*.md"), reverse=True):
        t = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", t, re.S)
        body = m.group(2) if m else t
        title = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), p.stem)
        summary = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("> ")), "")
        meta = dict(ln.split(":", 1) for ln in (m.group(1).splitlines() if m else []) if ":" in ln)
        items.append({"file": p.name, "week_start": meta.get("week_start", "").strip(), "week_end": meta.get("week_end", "").strip(),
                      "published": meta.get("published", "").strip(), "title": title, "summary": summary})
    (OUT / "index.json").write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"weekly index: {len(items)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", help="주의 마지막 날 (기본 오늘 KST)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    today = datetime.now(KST).date()
    end = date.fromisoformat(args.end) if args.end else today
    start, end = week_range(end)
    pack = build_pack(start, end)
    if args.dry_run:
        print(pack)
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1
    user = pack + "\n\n위 데이터 팩만 근거로 스킬 지침의 형식대로 주간 브리핑을 작성하라."
    body, meta = call_claude(PROMPT.read_text(encoding="utf-8"), user)
    print(f"stop={meta['stop']} in={meta['in']} out={meta['out']}")
    OUT.mkdir(parents=True, exist_ok=True)
    front = ("---\n" f"week_start: {start}\nweek_end: {end}\npublished: {today}\nmodel: {MODEL}\n"
             f"tokens_in: {meta['in']}\ntokens_out: {meta['out']}\n---\n\n")
    out = OUT / f"{end}.md"
    out.write_text(front + body.strip() + "\n", encoding="utf-8")
    print(f"written: {out.relative_to(ROOT)}")
    build_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())
