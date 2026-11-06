"""주요 지표 수집 → data/indicators.json

장중 시세: 네이버페이 증권 (지연 여부·시세 시각 포함)
과거 3개월 일봉: Yahoo Finance (yfinance) — 장중 시세와 섞어 계산하지 않는다.
"""
import sys
from common import DATA, get_json, keep_previous, load_json, now_iso, num, save_json

# (id, 네이버 코드, 네이버 category, 네이버 type, Yahoo 심볼, 이름, 단위, 소수자리)
INDICATORS = [
    ("kospi",  "KOSPI",    "domestic", "index",          "^KS11", "코스피",         "pt",  2),
    ("kosdaq", "KOSDAQ",   "domestic", "index",          "^KQ11", "코스닥",         "pt",  2),
    ("usdkrw", "FX_USDKRW","exchange", "exchange",       "KRW=X", "원/달러",        "원",  1),
    ("us10y",  "US10YT=RR","bond",     "governmentBond", "^TNX",  "미국 10년물",    "%",   3),
    ("nasdaq", ".IXIC",    "index",    "index",          "^IXIC", "나스닥",         "pt",  2),
    ("sp500",  ".INX",     "index",    "index",          "^GSPC", "S&P 500",        "pt",  2),
    ("dow",    ".DJI",     "index",    "index",          "^DJI",  "다우",           "pt",  2),
    ("vix",    ".VIX",     "index",    "index",          "^VIX",  "VIX",            "pt",  2),
    ("wti",    "CLcv1",    "energy",   "futures",        "CL=F",  "WTI",            "$",   2),
    ("gold",   "GCcv1",    "metals",   "futures",        "GC=F",  "금",             "$",   1),
    ("silver", "SIcv1",    "metals",   "futures",        "SI=F",  "은",             "$",   2),
    ("copper", "HGcv1",    "metals",   "futures",        "HG=F",  "구리",           "$",   3),
]
OUT = DATA / "indicators.json"


def naver_quote_url(code: str, category: str) -> str:
    if category == "domestic":
        return f"https://m.stock.naver.com/api/index/{code}/basic"
    if category == "index":
        return f"https://api.stock.naver.com/index/{code}/basic"
    if category == "exchange":
        return f"https://m.stock.naver.com/front-api/marketIndex/productDetail?category=exchange&reutersCode={code}"
    return f"https://m.stock.naver.com/front-api/marketIndex/productDetail?category={category}&reutersCode={code}"


def live_quote(code: str, category: str) -> dict:
    payload = get_json(naver_quote_url(code, category))
    q = payload.get("result", payload) if isinstance(payload, dict) else {}
    if payload.get("isSuccess") is False:
        raise ValueError("naver isSuccess=false")
    price = num(q.get("closePrice"))
    if not price or price <= 0:
        raise ValueError("no price")
    delay = num(q.get("delayTime"))
    return {
        "price": price,
        "change": num(q.get("compareToPreviousClosePrice") if q.get("compareToPreviousClosePrice") is not None else q.get("fluctuations")),
        "changePercent": num(q.get("fluctuationsRatio")),
        "quoteAt": q.get("localTradedAt"),
        "marketStatus": q.get("marketStatus") or "UNKNOWN",
        "delayLabel": "실시간" if delay == 0 else (f"{int(delay)}분 지연" if delay and delay > 0 else "지연 여부 미제공"),
    }


def history(symbol: str, digits: int) -> list[dict]:
    import yfinance as yf
    df = yf.Ticker(symbol).history(period="3mo", interval="1d", auto_adjust=False)
    if df is None or df.empty:
        return []
    return [
        {"date": idx.strftime("%Y-%m-%d"), "close": round(float(row["Close"]), digits)}
        for idx, row in df.iterrows() if row["Close"] == row["Close"]
    ]


def main() -> int:
    prev = {i["id"]: i for i in load_json(OUT, {}).get("items", [])}
    items = []
    for id_, code, cat, typ, ysym, name, unit, digits in INDICATORS:
        item = {"id": id_, "name": name, "unit": unit, "digits": digits, "status": "unavailable"}
        try:
            item.update(live_quote(code, cat))
            item["status"] = "ok"
        except Exception as e:
            print(f"{id_}: live FAIL {type(e).__name__}: {e}", file=sys.stderr)
        try:
            pts = history(ysym, digits)
            if pts:
                item["points"] = pts
                item["asOf"] = pts[-1]["date"]
                closes = [p["close"] for p in pts]
                item["low"], item["high"] = min(closes), max(closes)

                def perf(n):
                    return round((closes[-1] / closes[-1 - n] - 1) * 100, 2) if len(closes) > n else None
                item["perf"] = {"1w": perf(5), "1m": perf(21), "3m": perf(len(closes) - 1)}
                if item["status"] != "ok":  # 장중 시세 실패 시 일봉 종가라도 보여준다
                    item.update({"status": "ok", "price": closes[-1], "change": None, "changePercent": None,
                                 "quoteAt": pts[-1]["date"], "marketStatus": "CLOSE", "delayLabel": "일봉 종가"})
        except Exception as e:
            print(f"{id_}: history FAIL {type(e).__name__}: {e}", file=sys.stderr)
        item["collectedAt"] = now_iso()
        items.append(keep_previous(item, prev.get(id_)))
        print(f"{id_}: {items[-1]['status']} price={items[-1].get('price')} pts={len(items[-1].get('points') or [])}")
    save_json(OUT, {"schemaVersion": 1, "collectedAt": now_iso(),
                    "source": "장중 시세: 네이버페이 증권 · 일봉: Yahoo Finance", "items": items})
    return 0


if __name__ == "__main__":
    sys.exit(main())
