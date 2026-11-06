"""외국인 수급 × 지수 (장중 시간대별) 수집 → data/market.json
또한 하루 한 번 장 마감 후 외국인 순매수 합계를 data/flows_daily.json 에 누적한다.

출처: 네이버페이 증권 (m.stock.naver.com / api.stock.naver.com / stock.naver.com)
 - 지수 기본정보: /api/index/{code}/basic
 - 지수 분봉:    /chart/domestic/index/{code}?periodType=day
 - 투자자별 매매동향(시간대): /api/domestic/market/trend/time?tradeType=KRX&marketType={code}&bizdate=&startIdx=&pageSize=200
외국인 investorGubun = '9000'. 금액 단위: 현물 diffValue(원) → 억원, 선물 buyPrice/sellPrice(백만원) → 억원.
"""
import sys
from common import DATA, get_json, keep_previous, load_json, now_iso, num, save_json, today_kst

MARKETS = {"KOSPI": "코스피", "KOSDAQ": "코스닥", "FUT": "K200 선물"}
OUT = DATA / "market.json"
DAILY = DATA / "flows_daily.json"


def foreign_net_eok(code: str, row: dict | None):
    if row is None:
        return None
    if code == "FUT":
        buy, sell = num(row.get("buyPrice")), num(row.get("sellPrice"))
        return None if buy is None or sell is None else (buy - sell) / 100
    net = num(row.get("diffValue"))
    return None if net is None else net / 1e8


def collect_one(code: str) -> dict:
    basic = get_json(f"https://m.stock.naver.com/api/index/{code}/basic")
    chart = get_json(f"https://api.stock.naver.com/chart/domestic/index/{code}?periodType=day")
    base = str(chart.get("tradeBaseAt") or "")
    if not isinstance(chart.get("priceInfos"), list) or len(base) != 8:
        raise ValueError("invalid index chart")

    def page(i):
        return get_json(
            "https://stock.naver.com/api/domestic/market/trend/time"
            f"?tradeType=KRX&marketType={code}&bizdate={base}&startIdx={i}&pageSize=200"
        )

    first = page(0)
    content = first.get("content")
    if not isinstance(content, list):
        raise ValueError("invalid investor response")
    pages = 1 if first.get("last") or len(content) < 200 else min(4, int(first.get("totalPages") or 4))
    records = list(content)
    for i in range(1, pages):
        records += page(i).get("content") or []

    points = {}
    for r in records:
        t = str(r.get("time") or "")
        if r.get("bizdate") != base or len(t) != 6:
            continue
        foreign = next((n for n in (r.get("netAmounts") or []) if n.get("investorGubun") == "9000"), None)
        v = foreign_net_eok(code, foreign)
        if v is not None:
            points[f"{t[:2]}:{t[2:4]}"] = v
    prices = [
        {"time": f"{p['localDateTime'][8:10]}:{p['localDateTime'][10:12]}", "price": num(p.get("currentPrice"))}
        for p in chart["priceInfos"]
        if str(p.get("localDateTime", "")).startswith(base) and (num(p.get("currentPrice")) or 0) > 0
    ]
    if not points or not prices:
        raise ValueError("no same-session points")
    lo, hi = prices[0]["time"], prices[-1]["time"]
    pts = [{"time": t, "foreignNet": round(v, 1)} for t, v in sorted(points.items()) if lo <= t <= hi]
    return {
        "status": "ok", "code": code, "name": MARKETS[code],
        "date": f"{base[:4]}-{base[4:6]}-{base[6:]}", "unit": "억원",
        "price": num(basic.get("closePrice")), "changePercent": num(basic.get("fluctuationsRatio")),
        "priceTime": basic.get("localTradedAt"), "marketStatus": basic.get("marketStatus"),
        "previousClose": num(chart.get("lastClosePrice")),
        "points": pts, "prices": prices, "collectedAt": now_iso(),
    }


def update_daily(markets: dict) -> None:
    """각 시장의 당일 마지막 누적 외국인 순매수(억원)를 날짜별로 누적 저장 (최근 250거래일)."""
    daily = load_json(DAILY, {"unit": "억원", "rows": {}})
    rows = daily.setdefault("rows", {})
    for code, m in markets.items():
        if m.get("status") != "ok" or not m.get("points"):
            continue
        rows.setdefault(m["date"], {})[code] = m["points"][-1]["foreignNet"]
        rows[m["date"]][f"{code}_close"] = m.get("price")
    keys = sorted(rows)[-250:]
    daily["rows"] = {k: rows[k] for k in keys}
    daily["updatedAt"] = now_iso()
    save_json(DAILY, daily)


def main() -> int:
    prev = load_json(OUT, {}).get("markets", {})
    markets = {}
    for code in MARKETS:
        try:
            markets[code] = collect_one(code)
            print(f"{code}: ok {markets[code]['date']} points={len(markets[code]['points'])} last={markets[code]['points'][-1]}")
        except Exception as e:
            print(f"{code}: FAIL {type(e).__name__}: {e}", file=sys.stderr)
            markets[code] = keep_previous({"status": "unavailable", "code": code, "name": MARKETS[code]}, prev.get(code))
    save_json(OUT, {"schemaVersion": 1, "collectedAt": now_iso(),
                    "source": "네이버페이 증권 투자자별 매매동향 · 지수 시세", "markets": markets})
    update_daily(markets)
    return 0


if __name__ == "__main__":
    sys.exit(main())
