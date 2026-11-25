import re, requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "ko-KR,ko;q=0.9"}
r = requests.get("https://peptron.irupsite.co.kr/Default2.aspx", headers=UA, timeout=30)
t = r.text; print(r.status_code, len(t), r.encoding)
i = t.find('section007'); print("section007 at", i)
seg = t[i: i + 6000]
print(re.sub(r"\s+", " ", seg)[:5000])
print("\n--- count FAQ:", len(re.findall(r"자주\s*묻는\s*질문", t)))
