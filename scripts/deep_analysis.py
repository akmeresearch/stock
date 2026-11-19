"""기업 심층 분석글 생성 → data/reports/{ticker}_analysis_{YYYYMM}.md

DART 에서 가져오는 것
 1. 최신 사업보고서 + 직전 사업보고서 + 최신 분·반기보고서 원문 → 'II. 사업의 내용' 전체 (제품·원재료·생산능력·생산실적·가동률·매출실적·수주상황·연구개발·설비투자)
 2. 같은 문서의 재무제표 주석 중 영업부문·지역별 매출·주요 고객 창, 최대주주·직원 현황 창
 3. 5개년 연간 재무 (fnlttSinglAcntAll, 손익·재무상태·현금흐름 주요 계정)
 4. 12분기 손익 (data/financials/{ticker}.json)
 5. 최근 3년 단일판매·공급계약, 신규시설투자 등 주요 공시 본문 요약
사이트 수집 자료: 현재가·시총·PER·PBR (data/prices), 수주잔고 (data/backlog.json)

실행: python scripts/deep_analysis.py --ticker 031980 [--dry-run] [--model claude-opus-5-5]
환경변수: DART_API_KEY, ANTHROPIC_API_KEY
"""
import argparse
import io
import json
import os
import re
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, KST, ROOT, clean_markdown, get_json, load_json, num, now_iso  # noqa: E402

PROMPT = ROOT / "prompts" / "deep_analysis.md"
REPORTS = DATA / "reports"
MODEL = os.environ.get("ANALYSIS_MODEL", "claude-opus-5-5")
FALLBACK_MODEL = "claude-sonnet-5-5"
ANNUAL_LINES = [  # (라벨, 계정명 후보, 재무제표 구분)
    ("매출액", ("매출액", "수익(매출액)", "영업수익", "매출"), ("IS", "CIS")),
    ("매출원가", ("매출원가",), ("IS", "CIS")),
    ("매출총이익", ("매출총이익", "매출총이익(손실)"), ("IS", "CIS")),
    ("판매비와관리비", ("판매비와관리비", "판매비및관리비"), ("IS", "CIS")),
    ("영업이익", ("영업이익", "영업이익(손실)"), ("IS", "CIS")),
    ("당기순이익", ("당기순이익", "당기순이익(손실)"), ("IS", "CIS")),
    ("자산총계", ("자산총계",), ("BS",)),
    ("부채총계", ("부채총계",), ("BS",)),
    ("자본총계", ("자본총계",), ("BS",)),
    ("현금및현금성자산", ("현금및현금성자산",), ("BS",)),
    ("단기금융상품", ("단기금융상품", "단기금융자산"), ("BS",)),
    ("매출채권", ("매출채권", "매출채권및기타채권", "매출채권 및 기타채권"), ("BS",)),
    ("재고자산", ("재고자산",), ("BS",)),
    ("계약자산", ("계약자산",), ("BS",)),
    ("계약부채", ("계약부채", "선수금"), ("BS",)),
    ("유형자산", ("유형자산",), ("BS",)),
    ("단기차입금", ("단기차입금",), ("BS",)),
    ("장기차입금", ("장기차입금",), ("BS",)),
    ("영업활동현금흐름", ("영업활동현금흐름", "영업활동으로 인한 현금흐름", "영업활동으로인한현금흐름"), ("CF",)),
    ("투자활동현금흐름", ("투자활동현금흐름", "투자활동으로 인한 현금흐름", "투자활동으로인한현금흐름"), ("CF",)),
    ("유형자산의 취득", ("유형자산의 취득", "유형자산의취득", "유형자산 취득"), ("CF",)),
]


def eok(v) -> str:
    return "—" if v is None else f"{v / 1e8:,.0f}"


# ------------------------------------------------------------------ DART 원문
def dart_list(corp: str, key: str, years: int, pblntf_ty: str) -> list[dict]:
    end = date.today(); bgn = end - timedelta(days=365 * years + 30)
    out = []
    for page in range(1, 6):
        p = get_json("https://opendart.fss.or.kr/api/list.json", timeout=30, params={
            "crtfc_key": key, "corp_code": corp, "bgn_de": bgn.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"),
            "pblntf_ty": pblntf_ty, "page_no": page, "page_count": 100})
        if p.get("status") != "000":
            break
        out += p.get("list", [])
        if page >= int(p.get("total_page", 1)):
            break
    return out


def periodic_reports(corp: str, key: str) -> list[dict]:
    rows = []
    for f in dart_list(corp, key, 3, "A"):
        nm = f.get("report_nm", "")
        m = re.search(r"(분기보고서|반기보고서|사업보고서)\s*\((\d{4})\.(\d{2})\)", nm)
        if not m:
            continue
        rows.append({"rcept_no": f["rcept_no"], "rcept_dt": f["rcept_dt"], "report_nm": nm, "kind": m.group(1),
                     "ym": f"{m.group(2)}.{m.group(3)}"})
    rows.sort(key=lambda r: (r["ym"], r["rcept_dt"]), reverse=True)  # 정정본이 있으면 뒤 제출본 우선
    seen, uniq = set(), []
    for r in rows:
        if r["ym"] in seen:
            continue
        seen.add(r["ym"]); uniq.append(r)
    return uniq


def fetch_full_text(rcept_no: str, key: str) -> str:
    r = requests.get("https://opendart.fss.or.kr/api/document.xml", params={"crtfc_key": key, "rcept_no": rcept_no}, timeout=120)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".xml", ".html", ".htm"))]
        raw = " ".join(zf.read(n).decode("utf-8", errors="ignore") for n in names)
    # 표 구조를 조금 살린다: 행 끝에 줄바꿈, 셀 사이에 |
    raw = re.sub(r"</(tr|TR)>", "\n", raw)
    raw = re.sub(r"</(td|th|TD|TH)>", " | ", raw)
    raw = re.sub(r"</(p|P|div|DIV|h\d|H\d|li|LI)>", "\n", raw)
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def section(text: str, start_pat: str, end_pat: str, min_len: int = 3000, limit: int = 160_000) -> str:
    """start_pat 로 시작해 end_pat 직전까지. 목차에도 같은 제목이 있으므로 충분히 긴 구간을 고른다."""
    best = ""
    for m in re.finditer(start_pat, text):
        e = re.search(end_pat, text[m.end():])
        chunk = text[m.start(): m.end() + (e.start() if e else len(text))]
        if len(chunk) >= min_len and len(chunk) > len(best):
            best = chunk
    return best[:limit]


def windows(text: str, pats: list[str], span: int = 5000, max_windows: int = 4, last: bool = False) -> str:
    """패턴 주변 창. last=True 면 패턴별 마지막 출현(목차가 아닌 본문)만 쓴다."""
    if last:
        idx = sorted({ms[-1].start() for p in pats if (ms := list(re.finditer(p, text)))})
    else:
        idx = sorted({m.start() for p in pats for m in re.finditer(p, text)})
    chunks, last = [], -1
    for i in idx:
        if i < last:
            continue
        chunks.append(text[max(0, i - 300): i + span]); last = i + span
        if len(chunks) >= max_windows:
            break
    return "\n\n[...]\n\n".join(chunks)


def report_pack(r: dict, key: str, full: bool) -> str:
    text = fetch_full_text(r["rcept_no"], key)
    print(f"  {r['report_nm']} ({r['rcept_dt']}): {len(text):,} chars")
    parts = [f"=== DART {r['report_nm']} 접수 {r['rcept_dt']} (rcept_no {r['rcept_no']}) ==="]
    biz = section(text, r"II\.?\s*사업의\s*내용", r"III\.?\s*재무에\s*관한\s*사항", limit=160_000 if full else 90_000)
    parts.append("--- II. 사업의 내용 ---\n" + (biz or windows(text, [r"주요\s*제품", r"생산능력", r"가동률", r"수주상황", r"매출실적"], 6000, 6)))
    notes = windows(text, [r"영업부문", r"부문별\s*(매출|정보)", r"지역별\s*(매출|정보|수익)", r"주요\s*고객", r"외부고객"], 4500, 5)
    if notes:
        parts.append("--- 재무제표 주석: 부문·지역·고객 ---\n" + notes)
    if full:
        corp = windows(text, [r"최대주주\s*및\s*(그\s*)?특수관계인의\s*주식소유", r"직원\s*등의\s*현황", r"주요\s*종속회사", r"연결대상\s*종속회사", r"배당에\s*관한\s*사항", r"자기주식\s*취득\s*및\s*처분", r"소액주주"], 4000, 7, last=True)
        if corp:
            parts.append("--- 지배구조·종속회사·직원·배당 ---\n" + corp)
        mda = section(text, r"경영진단\s*및\s*분석의견|이사의\s*경영진단", r"IV\.|감사인의\s*감사의견", min_len=2000, limit=30_000)
        if mda:
            parts.append("--- 경영진단 ---\n" + mda)
    return "\n\n".join(parts)


def annual_table(corp: str, key: str, years: list[int]) -> str:
    rows = {}
    for y in years:
        for fs_div in ("CFS", "OFS"):
            try:
                p = get_json("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json", timeout=30, params={
                    "crtfc_key": key, "corp_code": corp, "bsns_year": y, "reprt_code": "11011", "fs_div": fs_div})
            except Exception as e:
                print(f"  annual {y} {fs_div}: {e}", file=sys.stderr); continue
            lst = p.get("list", []) if p.get("status") == "000" else []
            if not lst:
                continue
            rec = {"fs": fs_div}
            for label, names, sjs in ANNUAL_LINES:
                row = next((r for r in lst if r.get("sj_div") in sjs and r.get("account_nm", "").replace(" ", "") in [n.replace(" ", "") for n in names]), None)
                if row is None:
                    row = next((r for r in lst if r.get("sj_div") in sjs and any(n.replace(" ", "") in r.get("account_nm", "").replace(" ", "") for n in names)), None)
                if row is not None:
                    rec[label] = num(row.get("thstrm_amount"))
            rows[y] = rec
            break
    if not rows:
        return "연간 재무: 미제공"
    ys = sorted(rows)
    lines = [f"연간 재무 (DART fnlttSinglAcntAll, 사업보고서 기준, 단위 억원; 연결 {'CFS' if rows[ys[-1]]['fs'] == 'CFS' else '개별 OFS'})",
             "| 항목 | " + " | ".join(str(y) for y in ys) + " |", "| --- |" + " --- |" * len(ys)]
    for label, _, _ in ANNUAL_LINES:
        if any(label in rows[y] for y in ys):
            lines.append(f"| {label} | " + " | ".join(eok(rows[y].get(label)) for y in ys) + " |")
    # 파생 비율
    def ratio(a, b, y):
        va, vb = rows[y].get(a), rows[y].get(b)
        return "—" if va is None or not vb else f"{va / vb * 100:.1f}%"
    lines.append("| 매출총이익률(계산) | " + " | ".join(ratio("매출총이익", "매출액", y) for y in ys) + " |")
    lines.append("| 영업이익률(계산) | " + " | ".join(ratio("영업이익", "매출액", y) for y in ys) + " |")
    lines.append("| 부채비율(계산) | " + " | ".join(ratio("부채총계", "자본총계", y) for y in ys) + " |")
    return "\n".join(lines)


def quarterly_table(ticker: str) -> str:
    d = load_json(DATA / "financials" / f"{ticker}.json", {})
    q = d.get("quarters", {})
    if not q:
        return "분기 손익: 미제공"
    lines = ["분기 손익 (DART, 억원, 3개월; Q4는 연간−3분기누적 역산)", "| 분기 | 매출액 | 영업이익 | 당기순이익 | 영업이익률 |", "| --- | --- | --- | --- | --- |"]
    for k in sorted(q)[-12:]:
        r = q[k]; s, o, n = (r.get(x, {}).get("q") for x in ("매출액", "영업이익", "당기순이익"))
        lines.append(f"| {k} | {eok(s)} | {eok(o)} | {eok(n)} | {('—' if not s or o is None else f'{o / s * 100:.1f}%')} |")
    return "\n".join(lines)


def disclosures(corp: str, key: str) -> str:
    """최근 3년 주요 공시 중 계약·투자·증자 등 사업에 영향 큰 것 본문 발췌."""
    want = re.compile(r"공급계약|수주|신규시설투자|유상증자|무상증자|자기주식|타법인|영업양수|합병|분할|전환사채|신주인수권|주식분할|배당")
    rows = []
    for ty in ("B", "I"):
        rows += dart_list(corp, key, 3, ty)
    rows = [r for r in rows if want.search(r.get("report_nm", ""))]
    rows.sort(key=lambda r: r["rcept_dt"], reverse=True)
    out = [f"주요 공시 목록 (최근 3년, {len(rows)}건)"] + [f"- {r['rcept_dt']} {r['report_nm']}" for r in rows[:40]]
    detail = []
    for r in [r for r in rows if re.search(r"공급계약|신규시설투자|유상증자", r["report_nm"])][:10]:
        try:
            t = fetch_full_text(r["rcept_no"], key)
            i = max(t.find("계약금액"), t.find("투자금액"), t.find("자금조달"), 0)
            detail.append(f"--- {r['rcept_dt']} {r['report_nm']} ---\n{t[max(0, i - 400): i + 1600]}")
        except Exception as e:
            print(f"  disclosure {r['rcept_no']}: {e}", file=sys.stderr)
    return "\n".join(out) + ("\n\n" + "\n\n".join(detail) if detail else "")


def market_block(ticker: str, name: str) -> str:
    p = load_json(DATA / "prices" / f"{ticker}.json", {})
    inf = p.get("infos", {})
    lines = [f"시세 (네이버페이 증권, {str(p.get('quoteAt', ''))[:16]}): 현재가 {p.get('price')}원 ({p.get('changePercent')}%)"]
    for k in ("시총", "PER", "EPS", "추정PER", "추정EPS", "PBR", "BPS", "배당수익률", "52주 최고", "52주 최저", "외인소진율", "거래량"):
        if k in inf:
            lines.append(f"- {k}: {inf[k]}")
    pts = p.get("points") or []
    if len(pts) > 20:
        c = [x.get("close") for x in pts if x.get("close")]
        if c:
            lines.append(f"- 1년 주가: 최고 {max(c):,.0f} 최저 {min(c):,.0f}, 1년 전 {c[0]:,.0f} → 현재 {c[-1]:,.0f} ({(c[-1] / c[0] - 1) * 100:+.1f}%, 계산)")
    bl = load_json(DATA / "backlog.json", {})
    comp = (bl.get("companies") or {}).get(ticker)
    if comp and comp.get("quarters"):
        lines.append("사이트 수주잔고 추출 (DART 정기보고서 수주상황, 억원; 사업보고서는 수주상황 미기재인 경우 있음):")
        for k in sorted(comp["quarters"])[-10:]:
            r = comp["quarters"][k]
            if not r.get("disclosed"):
                lines.append(f"- {k}: 수주상황 미기재"); continue
            lines.append(f"- {k} ({r.get('as_of')}): 수주잔고 {r.get('backlog_eok')} 수주총액 {r.get('order_total_eok')} 기납품 {r.get('delivered_eok')} — {str(r.get('note', ''))[:120]}")
            for it in (r.get("items") or [])[:6]:
                lines.append(f"    · {it}")
    return "\n".join(lines)


# ------------------------------------------------------------------ Claude
def call_claude(system: str, user: str, model: str) -> tuple[str, dict]:
    from anthropic import Anthropic
    client = Anthropic()
    messages = [{"role": "user", "content": user}]
    body, meta = "", {"stop": "", "in": 0, "out": 0, "model": model}
    for _ in range(4):
        # 긴 출력은 SDK가 스트리밍을 요구한다
        with client.messages.stream(model=model, max_tokens=32000, system=system, messages=messages) as stream:
            for _ in stream.text_stream:
                pass
            resp = stream.get_final_message()
        chunk = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        body += chunk
        meta["stop"] = resp.stop_reason; meta["in"] += resp.usage.input_tokens; meta["out"] += resp.usage.output_tokens
        print(f"  {model}: stop={resp.stop_reason} in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
        if resp.stop_reason != "max_tokens":
            break
        messages += [{"role": "assistant", "content": chunk},
                     {"role": "user", "content": "출력이 잘렸다. 마지막 문장 바로 다음부터 이어서, 반복 없이 끝까지 작성하라."}]
    return body, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--dry-run", action="store_true", help="데이터 팩만 만들어 /tmp 에 저장")
    args = ap.parse_args()
    key = os.environ.get("DART_API_KEY", "")
    if not key:
        print("DART_API_KEY not set", file=sys.stderr); return 1
    wl = load_json(DATA / "watchlist.json", {})
    entry = next((s for s in wl.get("kr", []) if s["ticker"] == args.ticker), None)
    if not entry:
        print(f"{args.ticker} not in watchlist", file=sys.stderr); return 1
    corp = entry.get("dart_corp_code")
    if not corp:
        from resolve_corp_codes import fetch_corp_map
        corp = fetch_corp_map(key).get(args.ticker)
        if not corp:
            print("corp code not found", file=sys.stderr); return 1
    name = entry["name"]
    print(f"{name} ({args.ticker}, corp {corp}) model={args.model}")

    reps = periodic_reports(corp, key)
    annuals = [r for r in reps if r["kind"] == "사업보고서"]
    latest = reps[0] if reps else None
    picks = []
    if latest and latest["kind"] != "사업보고서":
        picks.append((latest, False))
    picks += [(a, True) for a in annuals[:2]]
    # 최신 분기와 같은 해 반기보고서도 (수주·가동률 반기 추이)
    halves = [r for r in reps if r["kind"] == "반기보고서" and r not in [p[0] for p in picks]]
    if halves:
        picks.append((halves[0], False))
    packs = []
    for r, full in picks:
        try:
            packs.append(report_pack(r, key, full))
        except Exception as e:
            print(f"  {r['report_nm']}: {e}", file=sys.stderr)
    this_year = date.today().year
    years = [this_year - i for i in range(1, 6)]
    fin = annual_table(corp, key, years)
    qtab = quarterly_table(args.ticker)
    disc = disclosures(corp, key)
    mkt = market_block(args.ticker, name)

    user = "\n\n".join([
        f"# 분석 대상: {name} ({args.ticker}, {entry.get('market', '')}, {entry.get('sector', '')}) — 작성 기준일 {date.today()} (KST)",
        "## 시세·밸류에이션\n" + mkt,
        "## 연간 재무\n" + fin,
        "## 분기 손익\n" + qtab,
        "## 주요 공시\n" + disc,
        "## DART 정기보고서 원문 발췌\n" + "\n\n".join(packs),
        "위 자료만 근거로 스킬 지침의 형식에 맞춰 기업 심층 분석글을 작성하라.",
    ])
    print(f"user message: {len(user):,} chars")
    if args.dry_run:
        out = Path("/tmp") / f"deep_{args.ticker}.txt"; out.write_text(user, encoding="utf-8"); print("saved", out); return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr); return 1
    system = PROMPT.read_text(encoding="utf-8")
    try:
        body, meta = call_claude(system, user, args.model)
    except Exception as e:
        print(f"  {args.model} failed ({e}); fallback {FALLBACK_MODEL}", file=sys.stderr)
        body, meta = call_claude(system, user, FALLBACK_MODEL)
    now = datetime.now(KST)
    out = REPORTS / f"{args.ticker}_analysis_{now:%Y%m}.md"
    front = ("---\n" f"ticker: {args.ticker}\nname: {name}\nperiod: 기업분석 {now:%Y-%m}\nkind: analysis\nsource_type: auto\n"
             f"published: {now:%Y-%m-%d}\nmodel: {meta['model']}\nsources: " + "; ".join(f"{r['report_nm']} {r['rcept_dt']}" for r, _ in picks) +
             f"\ntokens_in: {meta['in']}\ntokens_out: {meta['out']}\n---\n\n")
    out.write_text(front + clean_markdown(body.strip()) + "\n", encoding="utf-8")
    print(f"written: {out.relative_to(ROOT)} ({len(body):,} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
