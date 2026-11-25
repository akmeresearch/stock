import re, requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "ko-KR,ko;q=0.9"}
t = requests.get("https://peptron.irupsite.co.kr/Default2.aspx", headers=UA, timeout=30).text
i = t.find('id="section007"'); print("section007 div at", i)
seg = t[i: i + 9000]
print(re.sub(r"\s+", " ", seg)[:8000])
