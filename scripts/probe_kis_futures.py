"""진단용: KIS 선물 시세 — 종목코드 형식 후보를 넓게 시도."""
import os, sys, requests
sys.path.insert(0, os.path.dirname(__file__))
from collect_kis import get_token
from collect_overseas import KIS, kis_headers

key, secret = os.environ["KIS_APP_KEY"], os.environ["KIS_APP_SECRET"]
tok = get_token(key, secret)
codes = ["101W12", "101WC000", "101WC0", "101WC", "A01612", "101612", "A01W12", "A01WC000", "KR4101WC0000", "101W1200"]
for div in ("F", "CM", "EU", "JF"):
    for code in codes:
        try:
            r = requests.get(f"{KIS}/uapi/domestic-futureoption/v1/quotations/inquire-price",
                             params={"FID_COND_MRKT_DIV_CODE": div, "FID_INPUT_ISCD": code},
                             headers=kis_headers(tok, key, secret, "FHMIF10000000"), timeout=20)
            j = r.json(); o1 = j.get("output1") or {}
            print(f"div={div} code={code}: rt={j.get('rt_cd')} prpr={o1.get('futs_prpr')} vol={o1.get('acml_vol')} name={o1.get('hts_kor_isnm')} keys={len(o1)} msg={j.get('msg1')}")
        except Exception as e:
            print(f"div={div} code={code}: {e}")
