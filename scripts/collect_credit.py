"""고객예탁금·신용융자 잔고 (시장 전체, 일별) → data/credit.json
출처: 네이버페이 증권 증시자금동향  https://stock.naver.com/market/stock/kr/deposit
API: https://stock.naver.com/api/domestic/market/trendDeposit?startIdx=N&pageSize=200  (bizdate, customerDeposit, creditLoan; 억원)
"""
import sys
from common import DATA, get_json, load_json, now_iso, num, save_json

OUT = DATA / "credit.json"
SOURCE = "https://stock.naver.com/market/stock/kr/deposit"


def fetch_pages(n: int = 4) -> list[dict]:
    rows = []
    for i in range(n):
        payload = get_json(f"https://stock.naver.com/api/domestic/market/trendDeposit?startIdx={i}&pageSize=200", timeout=20)
        content = payload.get("content") if isinstance(payload, dict) else payload
        if not isinstance(content, list):
            break
        for r in content:
            b = str(r.get("bizdate", ""))
            dep, cr = num(r.get("customerDeposit")), num(r.get("creditLoan"))
            if len(b) == 8 and dep and dep > 0 and cr is not None and cr >= 0:
                rows.append({"date": f"{b[:4]}-{b[4:6]}-{b[6:]}", "deposit": dep, "credit": cr})
        if len(content) < 200 or (isinstance(payload, dict) and payload.get("last")):
            break
    return rows


def main() -> int:
    prev = load_json(OUT, {})
    merged = {p["date"]: p for p in prev.get("points", [])}
    try:
        new = fetch_pages()
        if len(new) < 2:
            raise ValueError("too few rows")
        merged.update({p["date"]: p for p in new})
        status = "ok"
    except Exception as e:
        print(f"credit: FAIL {type(e).__name__}: {e}", file=sys.stderr)
        status = "stale" if merged else "unavailable"
    points = [merged[d] for d in sorted(merged)][-1300:]  # 약 5년
    out = {"schemaVersion": 1, "status": status, "unit": "억원", "source": SOURCE,
           "collectedAt": now_iso(), "asOf": points[-1]["date"] if points else None, "points": points}
    save_json(OUT, out)
    if points:
        p = points[-1]
        print(f"credit: {status} asOf={p['date']} deposit={p['deposit']:,.0f} credit={p['credit']:,.0f} ratio={p['credit']/p['deposit']*100:.1f}% n={len(points)}")
    return 0 if status != "unavailable" else 1


if __name__ == "__main__":
    sys.exit(main())
