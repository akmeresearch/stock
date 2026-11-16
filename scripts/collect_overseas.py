"""야간 코스피200 선물 · 삼성전자 GDR · SK하이닉스 ADR · 코인 스냅샷 → data/overseas.json

- 야간선물: 한국투자증권 Open API 국내선물옵션 시세 (야간시장, KRX 18:00~06:00)
- GDR/ADR: Yahoo Finance (SMSN.IL 런던 USD, HXSCL 미국 OTC USD), 네이버 해외주식 보조
- 코인: 업비트 공개 API (KRW 마켓), 바이낸스 USDT (김치프리미엄 계산용)
환경변수: KIS_APP_KEY, KIS_APP_SECRET (야간선물), KIS_TOKEN_CACHE
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

import requests

from common import DATA, HEADERS, get_json, keep_previous, load_json, now_iso, num, save_json

OUT = DATA / "overseas.json"
KIS = "https://openapi.koreainvestment.com:9443"
YEAR_CODE = {2024: "U", 2025: "V", 2026: "W", 2027: "X", 2028: "Y", 2029: "Z"}


def front_month_codes(today: date | None = None) -> list[str]:
    """KOSPI200 선물 최근월물 KIS 단축코드 후보 (예: 101W12). 만기(둘째 목요일) 지나면 다음 분기월."""
    today = today or date.today()
    cands = []
    y, m = today.year, today.month
    for _ in range(3):
        qm = ((m - 1) // 3 + 1) * 3  # 3,6,9,12
        exp = date(y, qm, 1)
        thursdays = [exp + timedelta(days=d) for d in range(31) if (exp + timedelta(days=d)).month == qm and (exp + timedelta(days=d)).weekday() == 3]
        if y == today.year and qm == today.month and today > thursdays[1]:
            m = qm + 1
            if m > 12:
                m, y = 1, y + 1
            continue
        cands.append(f"101{YEAR_CODE.get(y, 'W')}{qm:02d}")
        m = qm + 1
        if m > 12:
            m, y = 1, y + 1
    return cands[:2]


def kis_headers(token, key, secret, tr_id):
    return {"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
            "appkey": key, "appsecret": secret, "tr_id": tr_id, "custtype": "P"}


def night_futures(token, key, secret) -> dict:
    """야간선물 현재가. 시장구분 코드는 KIS 문서상 CM(야간선물)을 우선 시도하고, 실패 시 F(주간)로 대조한다."""
    last_err = None
    for code in front_month_codes():
        for div in ("CM", "F"):
            try:
                r = requests.get(f"{KIS}/uapi/domestic-futureoption/v1/quotations/inquire-price",
                                 params={"FID_COND_MRKT_DIV_CODE": div, "FID_INPUT_ISCD": code},
                                 headers=kis_headers(token, key, secret, "FHMIF10000000"), timeout=20)
                r.raise_for_status()
                p = r.json()
                if p.get("rt_cd") != "0":
                    raise RuntimeError(f"{div}/{code} rt_cd={p.get('rt_cd')} {p.get('msg1')}")
                o1, o2 = p.get("output1", {}), p.get("output2", {})
                price = num(o1.get("futs_prpr"))
                if not price:
                    raise RuntimeError(f"{div}/{code} no futs_prpr; keys={list(o1)[:12]}")
                print(f"  night futures {div}/{code}: price={price} keys1={list(o1)[:25]} keys2={list(o2)[:20]}")
                return {"status": "ok", "code": code, "market_div": div, "name": o1.get("hts_kor_isnm") or "코스피200 선물",
                        "price": price, "change": num(o1.get("futs_prdy_vrss")), "changePercent": num(o1.get("futs_prdy_ctrt")),
                        "prevClose": num(o1.get("futs_prdy_clpr")), "open": num(o1.get("futs_oprc")), "high": num(o1.get("futs_hgpr")), "low": num(o1.get("futs_lwpr")),
                        "volume": num(o1.get("acml_vol")), "basis": num(o1.get("basis")), "theory": num(o1.get("futs_theory_pric") or o2.get("theory_price")),
                        "kospi200": num(o1.get("kospi200_nmix") or o2.get("bstp_nmix_prpr")), "raw1": o1, "raw2": o2, "collectedAt": now_iso()}
            except Exception as e:
                last_err = e
                print(f"  night futures try {div}/{code}: {e}", file=sys.stderr)
    return {"status": "unavailable", "error": str(last_err), "collectedAt": now_iso()}


def yahoo_quote(sym: str) -> dict:
    import yfinance as yf
    t = yf.Ticker(sym)
    hist = t.history(period="1mo", interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise ValueError("no history")
    closes = [float(c) for c in hist["Close"].tolist() if c == c]
    dates = [i.strftime("%Y-%m-%d") for i in hist.index]
    info = {}
    try:
        fi = t.fast_info
        info = {"last": float(fi.last_price) if fi.last_price else None, "prev": float(fi.previous_close) if fi.previous_close else None, "currency": fi.currency}
    except Exception:
        pass
    last = info.get("last") or closes[-1]
    prev = info.get("prev") or (closes[-2] if len(closes) > 1 else None)
    return {"price": last, "prevClose": prev, "change": (last - prev) if prev else None,
            "changePercent": ((last / prev - 1) * 100) if prev else None, "currency": info.get("currency") or "USD",
            "asOf": dates[-1], "points": [{"date": d, "close": round(c, 2)} for d, c in zip(dates, closes)]}


def depositary(usdkrw: float | None, prices: dict) -> list[dict]:
    """GDR/ADR 시세 + 원화 환산 + 국내 종가 대비 프리미엄."""
    items = []
    for sym, ticker, name, ratio, venue in (("SMSN.IL", "005930", "삼성전자 GDR", 25, "런던 LSE · USD"),
                                            ("HXSCL", "000660", "SK하이닉스 ADR", 1, "미국 OTC · USD")):
        it = {"id": sym, "ticker": ticker, "name": name, "venue": venue, "sharesPerUnit": ratio, "status": "unavailable"}
        try:
            it.update(yahoo_quote(sym)); it["status"] = "ok"
            krx = prices.get(ticker) or {}
            if usdkrw and krx.get("price"):
                implied = it["price"] * usdkrw / ratio
                it["impliedKrw"] = round(implied)
                it["krxPrice"] = krx["price"]; it["krxQuoteAt"] = krx.get("quoteAt")
                it["premiumPct"] = round((implied / krx["price"] - 1) * 100, 2)
            print(f"  {name}: {it['price']} {it['currency']} asOf={it['asOf']} implied={it.get('impliedKrw')} krx={it.get('krxPrice')} prem={it.get('premiumPct')}")
        except Exception as e:
            print(f"  {name}: FAIL {type(e).__name__}: {e}", file=sys.stderr)
        it["collectedAt"] = now_iso()
        items.append(it)
    return items


def crypto(usdkrw: float | None) -> dict:
    markets = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
    up = get_json("https://api.upbit.com/v1/ticker?markets=" + ",".join(markets), timeout=15)
    out = {}
    for t in up:
        sym = t["market"].split("-")[1]
        out[sym] = {"krw": t.get("trade_price"), "changePct24h": round(t.get("signed_change_rate", 0) * 100, 2),
                    "high24h": t.get("high_price"), "low24h": t.get("low_price"), "volKrw24h": t.get("acc_trade_price_24h")}
    try:
        bn = get_json("https://api.binance.com/api/v3/ticker/price?symbols=" + json.dumps([f"{s}USDT" for s in out]).replace(" ", ""), timeout=15)
        for b in bn:
            sym = b["symbol"].replace("USDT", "")
            usd = num(b.get("price"))
            if sym in out and usd:
                out[sym]["usd"] = usd
                if usdkrw:
                    out[sym]["kimchiPremiumPct"] = round((out[sym]["krw"] / (usd * usdkrw) - 1) * 100, 2)
    except Exception as e:
        print(f"  binance: {e}", file=sys.stderr)
    print(f"  crypto: " + ", ".join(f"{k} {v['krw']:,.0f}원 ({v['changePct24h']:+.1f}%, 김프 {v.get('kimchiPremiumPct')})" for k, v in out.items()))
    return {"status": "ok", "source": "업비트 KRW · 바이낸스 USDT", "items": out, "collectedAt": now_iso()}


def main() -> int:
    prev = load_json(OUT, {})
    ind = {i["id"]: i for i in load_json(DATA / "indicators.json", {}).get("items", [])}
    usdkrw = (ind.get("usdkrw") or {}).get("price")
    prices = {t: load_json(DATA / "prices" / f"{t}.json", {}) for t in ("005930", "000660")}
    out = {"schemaVersion": 1, "collectedAt": now_iso(), "usdkrw": usdkrw}

    key, secret = os.environ.get("KIS_APP_KEY", "").strip(), os.environ.get("KIS_APP_SECRET", "").strip()
    nf = {"status": "unavailable"}
    if key and secret:
        try:
            from collect_kis import get_token
            nf = night_futures(get_token(key, secret), key, secret)
        except Exception as e:
            print(f"  night futures: {type(e).__name__}: {e}", file=sys.stderr)
    out["nightFutures"] = keep_previous(nf, prev.get("nightFutures"))

    out["depositary"] = depositary(usdkrw, prices)
    try:
        out["crypto"] = crypto(usdkrw)
    except Exception as e:
        print(f"  crypto FAIL {e}", file=sys.stderr)
        out["crypto"] = keep_previous({"status": "unavailable"}, prev.get("crypto"))
    save_json(OUT, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
