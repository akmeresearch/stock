"""진단: SEC 엔드포인트별·UA별 응답 코드"""
import requests
UAS = ["AKME Research akmeresearch@users.noreply.github.com",
       "AKME Research stock site (akmeresearch@users.noreply.github.com)",
       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 akmeresearch@users.noreply.github.com"]
URLS = ["https://www.sec.gov/files/company_tickers.json", "https://data.sec.gov/submissions/CIK0001045810.json",
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=NVDA&type=8-K&output=atom",
        "https://www.sec.gov/Archives/edgar/data/1045810/index.json", "https://efts.sec.gov/LATEST/search-index?q=NVDA&forms=8-K"]
for ua in UAS:
    for u in URLS:
        try:
            r = requests.get(u, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate", "Host": u.split('/')[2]}, timeout=20)
            print(f"[{r.status_code}] ua={ua[:25]!r} {u[:70]} len={len(r.content)}")
        except Exception as e:
            print(f"[ERR] ua={ua[:25]!r} {u[:70]} {e}")
try:
    from curl_cffi import requests as c
    r = c.get(URLS[0], impersonate="chrome", timeout=20); print(f"[{r.status_code}] curl_cffi chrome {URLS[0]}")
    r = c.get(URLS[1], impersonate="chrome", headers={"User-Agent": UAS[0]}, timeout=20); print(f"[{r.status_code}] curl_cffi chrome+UA {URLS[1]}")
except Exception as e:
    print("curl_cffi", e)
