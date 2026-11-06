"""DART 단일회사 전체 재무제표 API로 분기별 핵심 손익을 가져온다.

- fnlttSinglAcntAll.json (연결 CFS 우선, 없으면 별도 OFS)
- 분기 손익: thstrm_amount = 당기 3개월, thstrm_add_amount = 누적
- 결과는 data/financials/{ticker}.json 에 저장 (종목 페이지와 리포트 맥락에 사용)
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

from common import DATA, get_json, now_iso, num

FIN_DIR = DATA / "financials"
REPRT = {"Q1": "11013", "Q2": "11012", "Q3": "11014", "Q4": "11011"}
# (라벨, 계정명 후보들) — 회사마다 표기가 조금씩 다르다
LINES = [
    ("매출액", ("매출액", "수익(매출액)", "영업수익", "매출")),
    ("영업이익", ("영업이익", "영업이익(손실)")),
    ("당기순이익", ("당기순이익", "당기순이익(손실)", "분기순이익", "분기순이익(손실)", "반기순이익", "반기순이익(손실)")),
]


def quarters_back(n: int, today: date | None = None) -> list[tuple[int, str]]:
    """오늘 기준 '공시가 나와 있을 법한' 최근 n개 분기 (연도, Qx). 분기 종료 후 45일 뒤부터 포함."""
    today = today or date.today()
    y, m, d = today.year, today.month, today.day
    # 가장 최근에 보고서가 나왔을 분기
    if (m, d) >= (11, 15):
        last = (y, 3)
    elif (m, d) >= (8, 15):
        last = (y, 2)
    elif (m, d) >= (5, 16):
        last = (y, 1)
    elif (m, d) >= (4, 1):
        last = (y - 1, 4)
    else:
        last = (y - 1, 3)
    out = []
    yy, q = last
    for _ in range(n):
        out.append((yy, f"Q{q}"))
        q -= 1
        if q == 0:
            q, yy = 4, yy - 1
    return out


def fetch_quarter(corp_code: str, year: int, q: str, api_key: str) -> dict | None:
    for fs_div in ("CFS", "OFS"):
        payload = get_json(
            "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
            params={"crtfc_key": api_key, "corp_code": corp_code, "bsns_year": year,
                    "reprt_code": REPRT[q], "fs_div": fs_div}, timeout=30,
        )
        if payload.get("status") != "000":
            continue
        rows = [r for r in payload.get("list", []) if r.get("sj_div") in ("IS", "CIS")]
        if not rows:
            continue
        out = {"year": year, "quarter": q, "fs_div": fs_div, "unit": "원"}
        for label, names in LINES:
            row = next((r for r in rows if r.get("account_nm", "").strip() in names), None)
            if row is None:
                continue
            # 3개월 값: Q1/Q2/Q3 는 thstrm_amount, Q4(사업보고서)는 연간만 있어 누적에서 역산 불가 → 연간값 저장
            cur = num(row.get("thstrm_amount"))
            acc = num(row.get("thstrm_add_amount"))
            prev = num(row.get("frmtrm_amount"))  # 전년 동기 3개월 (분기보고서) / 전년 연간 (사업보고서)
            out[label] = {"q": cur, "acc": acc if acc is not None else cur, "prev_year_q": prev}
        return out
    return None


def collect_company(ticker: str, corp_code: str, api_key: str, n_quarters: int = 12) -> dict:
    path = FIN_DIR / f"{ticker}.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"ticker": ticker, "quarters": {}}
    for year, q in quarters_back(n_quarters):
        key = f"{year}{q}"
        if key in data["quarters"]:
            continue
        try:
            row = fetch_quarter(corp_code, year, q, api_key)
        except Exception as e:
            print(f"  {ticker} {key}: {type(e).__name__}: {e}", file=sys.stderr)
            row = None
        if row:
            data["quarters"][key] = row
            print(f"  {ticker} {key}: {row.get('fs_div')} 매출 {fmt_eok(row.get('매출액', {}).get('q'))} 영업이익 {fmt_eok(row.get('영업이익', {}).get('q'))}")
    derive_q4(data)
    data["updatedAt"] = now_iso()
    FIN_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


def derive_q4(data: dict) -> None:
    """사업보고서(Q4)는 연간값만 있으므로 Q4 3개월 = 연간 − 3분기 누적 으로 역산한다."""
    q = data.get("quarters", {})
    for key, row in q.items():
        if not key.endswith("Q4") or row.get("derived"):
            continue
        q3 = q.get(key[:4] + "Q3")
        if not q3:
            continue
        ok = False
        for label, _ in LINES:
            annual = (row.get(label) or {}).get("q")
            acc3 = (q3.get(label) or {}).get("acc")
            if annual is not None and acc3 is not None:
                row[label]["annual"] = annual
                row[label]["q"] = annual - acc3
                ok = True
        row["derived"] = ok


def fmt_eok(v) -> str:
    return "—" if v is None else f"{v / 1e8:,.0f}억"


def context_table(data: dict, max_rows: int = 6) -> str:
    """리포트 프롬프트에 넣을 압축 표 (억원, 3개월 기준)."""
    keys = sorted(data.get("quarters", {}))[-max_rows:]
    if not keys:
        return "직전 분기 재무: 미제공"
    lines = ["직전 분기 재무 (DART 공시 기준, 단위 억원, 3개월 손익; Q4는 연간값일 수 있음)",
             "| 분기 | 매출액 | 영업이익 | 당기순이익 | 영업이익률 |", "| --- | --- | --- | --- | --- |"]
    for k in keys:
        r = data["quarters"][k]
        s, o, n = (r.get(x, {}).get("q") for x in ("매출액", "영업이익", "당기순이익"))
        opm = f"{o / s * 100:.1f}%" if s and o is not None else "—"
        lines.append(f"| {k} ({r.get('fs_div')}) | {fmt_eok(s)} | {fmt_eok(o)} | {fmt_eok(n)} | {opm} |")
    return "\n".join(lines)


if __name__ == "__main__":
    key = os.environ.get("DART_API_KEY", "")
    wl = json.loads((DATA / "watchlist.json").read_text(encoding="utf-8"))
    for s in wl["kr"]:
        if s.get("dart_corp_code"):
            print(s["name"])
            d = collect_company(s["ticker"], s["dart_corp_code"], key)
            print(context_table(d))
