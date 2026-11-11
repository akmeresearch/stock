"""한국투자증권 Open API — 관심종목 투자자별 순매수(일별) 수집 → data/flows/{ticker}.json

- 토큰: POST /oauth2/tokenP (실행마다 발급; 1일 유효)
- 투자자별 매매동향: GET /uapi/domestic-stock/v1/quotations/inquire-investor (tr_id FHKST01010900)
  → 최근 약 30거래일, 개인·외국인·기관 순매수 수량/대금, 종가
환경변수: KIS_APP_KEY, KIS_APP_SECRET
"""
import json
import os
import sys
import time

import requests

from common import DATA, HEADERS, keep_previous, load_json, now_iso, num, save_json

BASE = "https://openapi.koreainvestment.com:9443"
OUT = DATA / "flows"


def get_token(key: str, secret: str) -> str:
    r = requests.post(f"{BASE}/oauth2/tokenP", json={"grant_type": "client_credentials", "appkey": key, "appsecret": secret},
                      headers={"content-type": "application/json; charset=utf-8"}, timeout=20)
    r.raise_for_status()
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError(f"no access_token: {r.text[:200]}")
    return tok


def investor_trend(token: str, key: str, secret: str, code: str) -> list[dict]:
    r = requests.get(
        f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-investor",
        params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        headers={"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
                 "appkey": key, "appsecret": secret, "tr_id": "FHKST01010900", "custtype": "P"},
        timeout=20,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("rt_cd") != "0":
        raise RuntimeError(f"rt_cd={payload.get('rt_cd')} {payload.get('msg1')}")
    rows = []
    for o in payload.get("output", []):
        d = str(o.get("stck_bsop_date", ""))
        if len(d) != 8:
            continue
        rows.append({
            "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
            "close": num(o.get("stck_clpr")),
            "change": num(o.get("prdy_vrss")),
            # 순매수 수량(주) / 순매수 거래대금(원)
            "indiv_qty": num(o.get("prsn_ntby_qty")), "foreign_qty": num(o.get("frgn_ntby_qty")), "inst_qty": num(o.get("orgn_ntby_qty")),
            "indiv_amt": num(o.get("prsn_ntby_tr_pbmn")), "foreign_amt": num(o.get("frgn_ntby_tr_pbmn")), "inst_amt": num(o.get("orgn_ntby_tr_pbmn")),
        })
    rows.sort(key=lambda x: x["date"])
    return rows


def main() -> int:
    key, secret = os.environ.get("KIS_APP_KEY", "").strip(), os.environ.get("KIS_APP_SECRET", "").strip()
    if not key or not secret:
        print("KIS_APP_KEY / KIS_APP_SECRET not set — skip", file=sys.stderr)
        return 0
    wl = json.loads((DATA / "watchlist.json").read_text(encoding="utf-8"))
    try:
        token = get_token(key, secret)
    except Exception as e:
        print(f"token FAIL {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    for s in wl.get("kr", []):
        code = s["ticker"]
        path = OUT / f"{code}.json"
        prev = load_json(path, {})
        item = {"ticker": code, "name": s["name"], "status": "unavailable", "unit": {"qty": "주", "amt": "원"},
                "source": "한국투자증권 Open API 투자자별 매매동향"}
        try:
            new_rows = investor_trend(token, key, secret, code)
            # 이전 자료와 병합해 최대 250거래일 보관
            merged = {r["date"]: r for r in prev.get("rows", [])}
            merged.update({r["date"]: r for r in new_rows})
            item["rows"] = [merged[d] for d in sorted(merged)][-250:]
            item["status"] = "ok"
            last = item["rows"][-1] if item["rows"] else {}
            print(f"{code} {s['name']}: ok rows={len(item['rows'])} last={last.get('date')} foreign_amt={last.get('foreign_amt')} close={last.get('close')}")
        except Exception as e:
            print(f"{code} {s['name']}: FAIL {type(e).__name__}: {e}", file=sys.stderr)
        item["collectedAt"] = now_iso()
        save_json(path, keep_previous(item, prev))
        time.sleep(0.15)  # 초당 20건 제한 여유
    return 0


if __name__ == "__main__":
    sys.exit(main())
