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
        g = lambda k: infos.get(k) or None
        out.update({"marketCap": g("시총"), "per": g("PER"), "pbr": g("PBR"), "eps": g("EPS"),
                    "perEst": g("추정PER"), "high52": g("52주 최고"), "low52": g("52주 최저"),
                    "dividendYield": g("배당수익률"), "foreignRate": g("외인소진율")})
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


def collect_us(s: dict) -> None:
    import yfinance as yf
    code = s["ticker"]; path = OUT / f"{code}.json"; prev = load_json(path, {})
    item = {"ticker": code, "name": s["name"], "market": s.get("market"), "currency": "USD", "status": "unavailable"}
    try:
        t = yf.Ticker(code)
        df = t.history(period="1y", interval="1d", auto_adjust=False)
        pts = [{"date": i.strftime("%Y-%m-%d"), "close": round(float(r["Close"]), 2), "volume": int(r["Volume"] or 0)} for i, r in df.iterrows() if r["Close"] == r["Close"]]
        fi = t.fast_info
        last = float(fi.last_price) if fi.last_price else pts[-1]["close"]
        prevc = float(fi.previous_close) if fi.previous_close else (pts[-2]["close"] if len(pts) > 1 else None)
        item.update({"points": pts, "price": round(last, 2), "change": round(last - prevc, 2) if prevc else None,
                     "changePercent": round((last / prevc - 1) * 100, 2) if prevc else None,
                     "quoteAt": now_iso(), "marketStatus": "UNKNOWN",
                     "marketCap": f"${fi.market_cap / 1e9:,.1f}B" if fi.market_cap else None,
                     "high52": f"{fi.year_high:,.2f}" if fi.year_high else None, "low52": f"{fi.year_low:,.2f}" if fi.year_low else None})
        try:
            info = t.info or {}
            item["per"] = f"{info['trailingPE']:.1f}" if info.get("trailingPE") else None
            item["perEst"] = f"{info['forwardPE']:.1f}" if info.get("forwardPE") else None
            item["pbr"] = f"{info['priceToBook']:.2f}" if info.get("priceToBook") else None
            item["eps"] = f"{info['trailingEps']:.2f}" if info.get("trailingEps") else None
            item["dividendYield"] = f"{info['dividendYield']:.2f}%" if info.get("dividendYield") else None
        except Exception:
            pass
        item["status"] = "ok"
    except Exception as e:
        print(f"{code}: FAIL {type(e).__name__}: {e}", file=sys.stderr)
    item["collectedAt"] = now_iso()
    item = keep_previous(item, prev)
    save_json(path, item)
    print(f"{code} {s['name']}: {item['status']} price={item.get('price')} pts={len(item.get('points') or [])}")


def main() -> int:
    wl = json.loads((DATA / "watchlist.json").read_text(encoding="utf-8"))
    for s in wl.get("us", []):
        collect_us(s)
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
