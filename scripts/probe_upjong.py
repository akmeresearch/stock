"""업종 등락 소스 탐색 (진단용)."""
import io, json, requests, pandas as pd
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
for url in ["https://m.stock.naver.com/api/stocks/industry?page=1&pageSize=5",
            "https://m.stock.naver.com/api/industry?page=1&pageSize=5",
            "https://m.stock.naver.com/api/stocks/industry/KOSPI?page=1&pageSize=5",
            "https://m.stock.naver.com/api/upjong?page=1&pageSize=5",
            "https://m.stock.naver.com/api/stocks/up/KOSPI?page=1&pageSize=3"]:
    try:
        r = requests.get(url, headers={**UA, "Referer": "https://m.stock.naver.com/"}, timeout=15)
        print(url, r.status_code, r.text[:300].replace("\n", " "))
    except Exception as e:
        print(url, "ERR", e)
r = requests.get("https://finance.naver.com/sise/sise_group.naver?type=upjong", headers=UA, timeout=20)
html = r.content.decode("euc-kr", errors="replace")
print("sise_group", r.status_code, len(html), html.count("<table"))
try:
    tbs = pd.read_html(io.StringIO(html), flavor="lxml")
    for t in tbs: print(list(t.columns)[:6], len(t))
except Exception as e:
    print("read_html", e)
i = html.find("업종명"); print(html[i-200:i+400] if i > 0 else "no 업종명")
