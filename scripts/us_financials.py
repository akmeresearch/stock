"""미국 관심종목 분기 손익 (Yahoo quarterly income statement) → data/financials/{ticker}.json (USD)
국내와 같은 구조(매출액·영업이익·당기순이익, 3개월 기준)로 저장해 종목 페이지가 그대로 그린다. 분기 라벨은 회계분기 종료일이 속한 달력 분기.
"""
import json
import sys
from common import DATA, now_iso

FIN_DIR = DATA / "financials"
LINES = {"매출액": ("Total Revenue", "Operating Revenue"), "영업이익": ("Operating Income", "EBIT"), "당기순이익": ("Net Income", "Net Income Common Stockholders")}


def main() -> int:
    import yfinance as yf
    wl = json.loads((DATA / "watchlist.json").read_text(encoding="utf-8"))
    for s in wl.get("us", []):
        t = s["ticker"]; path = FIN_DIR / f"{t}.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"ticker": t, "currency": "USD", "quarters": {}}
        try:
            df = yf.Ticker(t).quarterly_income_stmt
            if df is None or df.empty:
                raise ValueError("empty")
            for col in df.columns:
                end = col.to_pydatetime()
                key = f"{end.year}Q{(end.month - 1) // 3 + 1}"
                row = {"fs_div": "CFS", "unit": "USD", "period_end": end.strftime("%Y-%m-%d")}
                for label, names in LINES.items():
                    v = next((df.at[n, col] for n in names if n in df.index and df.at[n, col] == df.at[n, col]), None)
                    if v is not None:
                        row[label] = {"q": float(v), "acc": None, "prev_year_q": None}
                data["quarters"][key] = row
            data["currency"] = "USD"; data["updatedAt"] = now_iso()
            FIN_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            ks = sorted(data["quarters"]); last = data["quarters"][ks[-1]]
            print(f"{t}: {len(ks)} quarters, last {ks[-1]} rev ${last.get('매출액', {}).get('q', 0) / 1e9:.2f}B")
        except Exception as e:
            print(f"{t}: FAIL {type(e).__name__}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
