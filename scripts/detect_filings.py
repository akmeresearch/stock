"""관심종목의 신규 실적 공시를 감지해 리포트를 자동 생성한다.

흐름
 1. DART list.json 으로 최근 N일 공시 목록 조회 (관심종목별)
 2. 실적 공시(잠정실적·분기/반기/사업보고서)만 필터
 3. data/filings.json 의 처리 이력에 없으면 → 직전 분기 재무 맥락을 붙여 generate_report.py 실행
 4. 처리 이력 기록. 같은 종목·분기에 더 상세한 보고서(분기보고서)가 나중에 오면 갱신 생성

실행: python scripts/detect_filings.py [--days 14] [--dry-run]
환경변수: DART_API_KEY, ANTHROPIC_API_KEY
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from common import DATA, ROOT, get_json, now_iso
import dart_financials as fin

STATE = DATA / "filings.json"
REPORTS = DATA / "reports"

# 보고서명 → (종류, 상세도). 상세도가 높은 공시가 나중에 오면 리포트를 갱신한다.
KINDS = [
    (re.compile(r"영업\s*\(?잠정\)?\s*실적|잠정\s*실적"), "잠정실적", 1),
    (re.compile(r"^(\[기재정정\]\s*)?분기보고서"), "분기보고서", 2),
    (re.compile(r"^(\[기재정정\]\s*)?반기보고서"), "반기보고서", 2),
    (re.compile(r"^(\[기재정정\]\s*)?사업보고서"), "사업보고서", 2),
]


def classify(report_nm: str):
    for rx, kind, level in KINDS:
        if rx.search(report_nm):
            return kind, level
    return None, 0


def period_of(kind: str, report_nm: str, rcept_dt: str) -> str:
    """공시 종류·이름·접수일에서 대상 분기(YYYYQn)를 정한다."""
    m = re.search(r"\((\d{4})\.(\d{2})\)", report_nm)  # 분기보고서 (2026.09)
    if m:
        y, mm = int(m.group(1)), int(m.group(2))
        return f"{y}Q{(mm - 1) // 3 + 1}"
    y, mm = int(rcept_dt[:4]), int(rcept_dt[4:6])
    # 잠정실적: 1~2월 → 전년 Q4, 4~5월 → Q1, 7~8월 → Q2, 10~11월 → Q3
    if mm <= 3:
        return f"{y - 1}Q4"
    return f"{y}Q{(mm - 1) // 3}"


def list_filings(corp_code: str, api_key: str, days: int) -> list[dict]:
    end = date.today()
    bgn = end - timedelta(days=days)
    payload = get_json("https://opendart.fss.or.kr/api/list.json", timeout=30, params={
        "crtfc_key": api_key, "corp_code": corp_code,
        "bgn_de": bgn.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"),
        "page_count": 100,
    })
    if payload.get("status") == "013":  # 조회 결과 없음
        return []
    if payload.get("status") != "000":
        raise RuntimeError(f"DART list status={payload.get('status')} {payload.get('message')}")
    return payload.get("list", [])


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"seen": {}, "reports": {}}


def save_state(state: dict) -> None:
    state["updatedAt"] = now_iso()
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def generate(ticker: str, period: str, rcept_no: str, context_file: Path, kind: str) -> bool:
    cmd = [sys.executable, str(ROOT / "scripts" / "generate_report.py"),
           "--ticker", ticker, "--period", period, "--rcept", rcept_no,
           "--source", str(context_file), "--kind", kind]
    print("  run:", " ".join(cmd[2:]))
    return subprocess.call(cmd) == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    api_key = os.environ.get("DART_API_KEY", "")
    if not api_key:
        print("DART_API_KEY not set", file=sys.stderr)
        return 1

    wl = json.loads((DATA / "watchlist.json").read_text(encoding="utf-8"))
    state = load_state()
    generated = 0

    for s in wl.get("kr", []):
        corp = s.get("dart_corp_code")
        if not corp:
            continue
        try:
            filings = list_filings(corp, api_key, args.days)
        except Exception as e:
            print(f"{s['name']}: list FAIL {e}", file=sys.stderr)
            continue
        cands = []
        for f in filings:
            kind, level = classify(f.get("report_nm", ""))
            if kind:
                cands.append((f, kind, level))
        print(f"{s['name']}: {len(filings)} filings, {len(cands)} earnings-related")

        for f, kind, level in sorted(cands, key=lambda x: x[0]["rcept_dt"]):
            rcept = f["rcept_no"]
            period = period_of(kind, f["report_nm"], f["rcept_dt"])
            key = f"{s['ticker']}_{period}"
            done = state["reports"].get(key, {})
            if rcept in state["seen"]:
                continue
            state["seen"][rcept] = {"ticker": s["ticker"], "kind": kind, "period": period,
                                    "report_nm": f["report_nm"], "rcept_dt": f["rcept_dt"]}
            if done and done.get("level", 0) >= level:
                print(f"  skip {f['report_nm']} ({rcept}) — {key} already has level {done.get('level')}")
                continue
            print(f"  NEW {f['report_nm']} ({rcept}, {f['rcept_dt']}) → {key}")
            if args.dry_run:
                continue
            try:
                fdata = fin.collect_company(s["ticker"], corp, api_key)
                ctx = fin.context_table(fdata)
            except Exception as e:
                print(f"  financial context FAIL {e}", file=sys.stderr)
                ctx = "직전 분기 재무: 미제공"
            ctx_file = Path("/tmp") / f"ctx_{s['ticker']}_{period}.txt"
            ctx_file.write_text(ctx, encoding="utf-8")
            ok = generate(s["ticker"], period, rcept, ctx_file, kind)
            if ok:
                state["reports"][key] = {"rcept_no": rcept, "kind": kind, "level": level, "at": now_iso()}
                generated += 1
            else:
                print(f"  generate FAIL {key}", file=sys.stderr)
                state["seen"].pop(rcept, None)  # 다음 실행에서 재시도
            save_state(state)

    save_state(state)
    print(f"\ngenerated {generated} report(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
