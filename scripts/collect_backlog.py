"""반도체 소부장 수주잔고 — DART 분기·반기·사업보고서의 '수주상황' 표를 Claude로 구조화 추출 → data/backlog.json

흐름
 1. data/backlog_watch.json 의 기업별로 DART 정기공시 목록(최근 N년) 조회
 2. 아직 추출하지 않은 보고서 원문을 받아 '수주' 관련 구간만 잘라
 3. Claude에 JSON 추출 요청 (수주총액·기납품액·수주잔고, 단위, 기준일, 품목별)
 4. 분기 키(YYYYQn)로 저장. 정정보고서가 나오면 다시 추출해 덮어씀
실행: python scripts/collect_backlog.py [--years 3] [--limit N] [--dry-run]
환경변수: DART_API_KEY, ANTHROPIC_API_KEY
"""
import argparse
import io
import json
import os
import re
import sys
import zipfile
from datetime import date, timedelta

import requests

from common import DATA, get_json, load_json, now_iso, save_json
from resolve_corp_codes import fetch_corp_map

WATCH = DATA / "backlog_watch.json"
OUT = DATA / "backlog.json"
MODEL = os.environ.get("BACKLOG_MODEL", os.environ.get("REPORT_MODEL", "claude-sonnet-5-5"))
UNIT_MULT = {"원": 1e-8, "천원": 1e-5, "백만원": 1e-2, "억원": 1.0, "십억원": 10.0, "조원": 1e4}

SYSTEM = """너는 한국 상장사 정기보고서에서 '수주상황' 표를 읽어 구조화하는 분석가다.
입력은 보고서 본문 중 수주 관련 부분을 잘라낸 텍스트다. 아래 JSON만 출력한다(설명·마크다운 금지).

{
  "disclosed": true|false,            // 수주상황(수주잔고) 수치가 실제로 공시돼 있으면 true. "해당사항 없음"이거나 표가 없으면 false
  "as_of": "YYYY-MM-DD" | null,       // 표의 기준일 (보고서 기준일)
  "unit": "원"|"천원"|"백만원"|"억원"|"십억원"|"조원" | null,   // 표에 적힌 금액 단위 ("(단위: 백만원)" 등)
  "order_total": number | null,       // 수주총액 합계 (표 단위 그대로)
  "delivered": number | null,         // 기납품액 합계
  "backlog": number | null,           // 수주잔고 합계. 합계 행이 없으면 품목별 수주잔고를 더한 값
  "items": [ {"name": "...", "backlog": number} ],   // 품목/사업부별 수주잔고 (있으면, 최대 8개)
  "note": "..."                       // 특이사항 한 줄 (예: 단위 혼재, 일부 품목만 공시, 수주잔고 대신 수주총액만 있음)
}
규칙: 숫자는 표에서 그대로(쉼표 제거). 추정 금지. 합계 행("합계","계")이 있으면 그 값을 쓴다. 금액이 괄호면 음수. 수주잔고 열이 없고 수주총액·기납품액만 있으면 backlog = order_total - delivered 로 계산하고 note에 '계산'이라고 적는다."""


def list_reports(corp: str, key: str, years: int) -> list[dict]:
    end = date.today(); bgn = end - timedelta(days=365 * years + 30)
    out = []
    for page in range(1, 4):
        p = get_json("https://opendart.fss.or.kr/api/list.json", timeout=30, params={
            "crtfc_key": key, "corp_code": corp, "bgn_de": bgn.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"),
            "pblntf_ty": "A", "page_no": page, "page_count": 100})
        if p.get("status") != "000":
            break
        out += p.get("list", [])
        if page >= int(p.get("total_page", 1)):
            break
    rows = []
    for f in out:
        nm = f.get("report_nm", "")
        m = re.search(r"(분기보고서|반기보고서|사업보고서)\s*\((\d{4})\.(\d{2})\)", nm)
        if not m:
            continue
        y, mm = int(m.group(2)), int(m.group(3))
        rows.append({"rcept_no": f["rcept_no"], "rcept_dt": f["rcept_dt"], "report_nm": nm,
                     "period": f"{y}Q{(mm - 1) // 3 + 1}", "corrected": "정정" in nm})
    return rows


def fetch_full_text(rcept_no: str, key: str) -> str:
    r = requests.get("https://opendart.fss.or.kr/api/document.xml", params={"crtfc_key": key, "rcept_no": rcept_no}, timeout=90)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".xml", ".html", ".htm"))]
        # 본문이 여러 파일로 나뉜 경우 모두 합침
        raw = " ".join(zf.read(n).decode("utf-8", errors="ignore") for n in names)
    text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", text).strip()


def order_windows(text: str, max_windows: int = 3, span: int = 4500) -> str:
    """'수주' 표 주변만 잘라낸다. 우선순위: 수주상황 > 수주잔고 > 수주총액."""
    idx = []
    for pat in (r"수주\s*상황", r"수주\s*잔고", r"수주\s*총액"):
        idx += [m.start() for m in re.finditer(pat, text)]
    idx = sorted(set(idx))
    chunks, last = [], -1
    for i in idx:
        if i < last:
            continue
        s = max(0, i - 400); e = min(len(text), i + span)
        chunks.append(text[s:e]); last = e
        if len(chunks) >= max_windows:
            break
    return "\n\n[...]\n\n".join(chunks)


def extract(chunk: str, name: str, period: str) -> dict:
    from anthropic import Anthropic
    client = Anthropic()
    user = f"회사: {name}\n보고서 분기: {period}\n\n=== 본문 발췌 ===\n{chunk}\n\n위 발췌에서 수주상황을 JSON으로."
    resp = client.messages.create(model=MODEL, max_tokens=1200, system=SYSTEM, messages=[{"role": "user", "content": user}])
    txt = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.M).strip()
    data = json.loads(txt)
    data["_tokens"] = {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}
    return data


def to_eok(v, unit):
    if v is None or unit not in UNIT_MULT:
        return None
    return round(float(v) * UNIT_MULT[unit], 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--limit", type=int, default=60, help="이번 실행에서 추출할 최대 보고서 수 (비용 제한)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    key = os.environ.get("DART_API_KEY", "")
    if not key:
        print("DART_API_KEY not set", file=sys.stderr); return 1

    watch = load_json(WATCH, {"companies": []})
    out = load_json(OUT, {"schemaVersion": 1, "unit": "억원", "companies": {}})
    comps = out.setdefault("companies", {})
    corp_map = None
    done = 0
    for c in watch["companies"]:
        t = c["ticker"]
        entry = comps.setdefault(t, {"ticker": t, "name": c["name"], "segment": c.get("segment", ""), "corp_code": c.get("corp_code", ""), "quarters": {}})
        entry["name"], entry["segment"] = c["name"], c.get("segment", "")
        if not entry.get("corp_code"):
            corp_map = corp_map or fetch_corp_map(key)
            entry["corp_code"] = corp_map.get(t, "")
            if not entry["corp_code"]:
                print(f"{c['name']}: corp code NOT FOUND", file=sys.stderr); continue
        try:
            reports = list_reports(entry["corp_code"], key, args.years)
        except Exception as e:
            print(f"{c['name']}: list FAIL {e}", file=sys.stderr); continue
        # 분기별 최신 접수(정정 포함)만
        latest = {}
        for r in sorted(reports, key=lambda x: x["rcept_dt"]):
            latest[r["period"]] = r
        todo = [r for p_, r in sorted(latest.items()) if comps[t]["quarters"].get(p_, {}).get("rcept_no") != r["rcept_no"]]
        print(f"{c['name']}: {len(reports)} reports, {len(todo)} to extract")
        for r in todo:
            if done >= args.limit:
                break
            if args.dry_run:
                print(f"  would extract {r['period']} {r['report_nm']} ({r['rcept_no']})"); continue
            try:
                text = fetch_full_text(r["rcept_no"], key)
                chunk = order_windows(text)
                if not chunk:
                    comps[t]["quarters"][r["period"]] = {"rcept_no": r["rcept_no"], "rcept_dt": r["rcept_dt"], "disclosed": False, "note": "수주 관련 문구 없음", "extractedAt": now_iso()}
                    print(f"  {r['period']}: no 수주 text"); done += 1; continue
                d = extract(chunk, c["name"], r["period"])
                unit = d.get("unit")
                q = {"rcept_no": r["rcept_no"], "rcept_dt": r["rcept_dt"], "report_nm": r["report_nm"], "disclosed": bool(d.get("disclosed")),
                     "as_of": d.get("as_of"), "unit": unit, "note": d.get("note", ""),
                     "backlog_eok": to_eok(d.get("backlog"), unit), "order_total_eok": to_eok(d.get("order_total"), unit), "delivered_eok": to_eok(d.get("delivered"), unit),
                     "items": [{"name": i.get("name"), "backlog_eok": to_eok(i.get("backlog"), unit)} for i in (d.get("items") or [])[:8]],
                     "tokens": d.get("_tokens"), "extractedAt": now_iso()}
                comps[t]["quarters"][r["period"]] = q
                print(f"  {r['period']}: disclosed={q['disclosed']} backlog={q['backlog_eok']}억 unit={unit} note={q['note'][:40]}")
                done += 1
            except Exception as e:
                print(f"  {r['period']} FAIL {type(e).__name__}: {e}", file=sys.stderr)
        out["collectedAt"] = now_iso()
        save_json(OUT, out)
    print(f"extracted {done}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
