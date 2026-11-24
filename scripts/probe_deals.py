import requests, re
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
for url in [
  'https://news.google.com/rss/search?q=%22Eli+Lilly%22+(acquisition+OR+acquire+OR+acquires+OR+licensing+OR+%22license+agreement%22+OR+collaboration+OR+%22to+buy%22)&hl=en-US&gl=US&ceid=US:en',
  'https://news.google.com/rss/search?q=%EC%9D%BC%EB%9D%BC%EC%9D%B4%EB%A6%B4%EB%A6%AC+(%EC%9D%B8%EC%88%98+OR+%EA%B8%B0%EC%88%A0%EC%9D%B4%EC%A0%84+OR+%EB%9D%BC%EC%9D%B4%EC%84%A0%EC%8A%A4+OR+%EA%B3%84%EC%95%BD)&hl=ko&gl=KR&ceid=KR:ko',
  'https://investor.lilly.com/rss/news-releases.xml',
  'https://investor.lilly.com/news-releases',
  'https://www.lilly.com/news/press-releases',
  'https://efts.sec.gov/LATEST/search-index?q=%22Eli%20Lilly%22&forms=8-K',
]:
    try:
        r = requests.get(url, headers=UA, timeout=30)
        t = r.text
        items = re.findall(r"<item>.*?<title>(.*?)</title>.*?<pubDate>(.*?)</pubDate>", t, re.S)
        print(f"\n##### {url[:90]} -> {r.status_code} {len(t):,} chars, items={len(items)}")
        for ti, d in items[:6]: print("   ", d[:16], "|", re.sub(r"<!\[CDATA\[|\]\]>", "", ti)[:110])
        if not items: print("   ", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))[:400])
    except Exception as e:
        print(f"\n##### {url[:90]} ERR {e}")
from curl_cffi import requests as cffi
r = cffi.get("https://data.sec.gov/submissions/CIK0000059478.json", impersonate="chrome", timeout=30)
j = r.json(); rc = j["filings"]["recent"]
print("\n##### SEC Lilly submissions", r.status_code, j.get("name"))
for i in range(12): print("   ", rc["filingDate"][i], rc["form"][i], rc["items"][i] if rc.get("items") else "", rc["primaryDocument"][i][:50])
