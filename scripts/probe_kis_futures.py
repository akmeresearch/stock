"""진단용: KIS 선물 시세 응답 원문을 여러 시장코드·종목코드 조합으로 찍어본다."""
import json, os, sys, requests
sys.path.insert(0, os.path.dirname(__file__))
from collect_kis import get_token
from collect_overseas import KIS, kis_headers, front_month_codes

key, secret = os.environ["KIS_APP_KEY"], os.environ["KIS_APP_SECRET"]
tok = get_token(key, secret)
codes = front_month_codes() + ["101W12", "101WC000", "K200F", "101"]
for div in ("F", "CM", "EU", "JF", "O"):
    for code in codes[:3]:
        for tr in ("FHMIF10000000",):
            try:
                r = requests.get(f"{KIS}/uapi/domestic-futureoption/v1/quotations/inquire-price",
                                 params={"FID_COND_MRKT_DIV_CODE": div, "FID_INPUT_ISCD": code},
                                 headers=kis_headers(tok, key, secret, tr), timeout=20)
                body = r.text[:900].replace("\n", " ")
                print(f"[{r.status_code}] div={div} code={code} tr={tr} -> {body}")
            except Exception as e:
                print(f"div={div} code={code}: {e}")
# 야간선물 전용 후보: 선물옵션 야간 현재가 (tr_id 후보)
for tr, path in (("FHMIF10000000", "/uapi/domestic-futureoption/v1/quotations/inquire-price"),
                 ("FHPIF05030100", "/uapi/domestic-futureoption/v1/quotations/display-board-futures"),):
    for div in ("CM", "F"):
        r = requests.get(f"{KIS}{path}", params={"FID_COND_MRKT_DIV_CODE": div, "FID_INPUT_ISCD": codes[0], "FID_COND_SCR_DIV_CODE": "20503", "FID_COND_MRKT_CLS_CODE": "", "FID_MTRT_CNT": "", "FID_MRKT_CLS_CODE": ""},
                        headers=kis_headers(tok, key, secret, tr), timeout=20)
    print(f"[{r.status_code}] {tr} {path} div={div} -> {r.text[:600]}")
