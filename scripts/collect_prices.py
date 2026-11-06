"""관심종목 시세 → data/prices/{ticker}.json
 - 현재가·등락: 네이버페이 증권 m.stock.naver.com/api/stock/{code}/basic
 - 1년 일봉: Yahoo Finance ({code}.KS / {code}.KQ)
"""
import json
import sys
from common import DATA, get_json, keep_previous, load_json, now_iso, num, save_json

OUT = DATA / "prices"


def live(code: str) -> dict:
    q = get_json(f"https://m.stock.naver.com/api/stock/{code}/basic")
    price = num(q.get("closePrice"))
    if not price:
        raise ValueError("no price")
    out = {"price": price, "change": num(q.get("compareToPreviousClosePrice")),
           "changePercent": num(q.get("fluctuationsRatio")), "quoteAt": q.get("localTradedAt"),
           "marketStatus": q.get("marketStatus")}
    try:  # 시총·PER·PBR·52주 등은 /integration 의 totalInfos (한글 라벨 → 값 문자열)
        integ = get_json(f"https://m.stock.naver.com/api/stock/{code}/integration")
        infos = {str(i.get("key", "")).strip(): str(i.get("value", "")).strip() for i in integ.get("totalInfos", [])}
        out["infos"] = infos
        pick = lambda *subs: next((v for k, v in infos.items() if all(x in k for x in subs)), None)
        out["marketCap"] = pick("시가총액")
        out["per"] = pick("PER")
        out["pbr"] = pick("PBR")
        out["eps"] = pick("EPS")
        out["high52"] = pick("52주", "고") or pick("52주", "최고")
        out["low52"] = pick("52주", "저") or pick("52주", "최저")
        out["dividendYield"] = pick("배당수익률")
        out["foreignRate"] = pick("외국인")
        print(f"  {code} totalInfos keys: {list(infos)[:20]}")
    except Exception as e:
        print(f"  {code} integration FAIL {type(e).__name__}: {e}", file=sys.stderr)
    return out


def history(code: str, market: str) -> list[dict]:
    import yfinance as yf
    sym = f"{code}.{'KQ' if market == 'KOSDAQ' else 'KS'}"
    df = yf.Ticker(sym).history(period="1y", interval="1d", auto_adjust=False)
    if df is None or df.empty:
        return []
    return [{"date": i.strftime("%Y-%m-%d"), "close": round(float(r["Close"]), 0), "volume": int(r["Volume"])}
            for i, r in df.iterrows() if r["Close"] == r["Close"]]


def main() -> int:
    wl = json.loads((DATA / "watchlist.json").read_text(encoding="utf-8"))
    for s in wl.get("kr", []):
        code = s["ticker"]
        path = OUT / f"{code}.json"
        prev = load_json(path, {})
        item = {"ticker": code, "name": s["name"], "market": s.get("market"), "status": "unavailable"}
        try:
            item.update(live(code)); item["status"] = "ok"
        except Exception as e:
            print(f"{code}: live FAIL {type(e).__name__}: {e}", file=sys.stderr)
        try:
            pts = history(code, s.get("market", "KOSPI"))
            if pts:
                item["points"] = pts
                if item["status"] != "ok":
                    item.update({"status": "ok", "price": pts[-1]["close"], "quoteAt": pts[-1]["date"], "marketStatus": "CLOSE"})
        except Exception as e:
            print(f"{code}: history FAIL {type(e).__name__}: {e}", file=sys.stderr)
        item["collectedAt"] = now_iso()
        item = keep_previous(item, prev)
        save_json(path, item)
        print(f"{code} {s['name']}: {item['status']} price={item.get('price')} pts={len(item.get('points') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
