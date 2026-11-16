"""코스피·코스닥 일봉 5년 (Yahoo) → data/index_history.json  (기간 조회 차트용)"""
import sys
from common import DATA, load_json, now_iso, save_json

OUT = DATA / "index_history.json"
SYMS = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}


def main() -> int:
    import yfinance as yf
    prev = load_json(OUT, {})
    out = {"schemaVersion": 1, "collectedAt": now_iso(), "source": "Yahoo Finance 일봉", "series": {}}
    for code, sym in SYMS.items():
        merged = {p["date"]: p for p in (prev.get("series", {}).get(code) or [])}
        try:
            # 처음(또는 짧게만 쌓인 경우)엔 전체 이력, 이후엔 최근 3개월만 받아 병합
            df = yf.Ticker(sym).history(period="max" if len(merged) < 3000 else "3mo", interval="1d", auto_adjust=False)
            for i, r in df.iterrows():
                if r["Close"] == r["Close"]:
                    merged[i.strftime("%Y-%m-%d")] = {"date": i.strftime("%Y-%m-%d"), "close": round(float(r["Close"]), 2)}
            print(f"{code}: {len(merged)} days, last {max(merged)}")
        except Exception as e:
            print(f"{code}: FAIL {type(e).__name__}: {e}", file=sys.stderr)
        pts = [merged[d] for d in sorted(merged)]
        out["series"][code] = pts  # 전체 이력 (Yahoo 제공 범위: 코스피 1997~)
    save_json(OUT, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
