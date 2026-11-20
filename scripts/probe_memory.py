"""메모리 가격 소스 탐색 2 (진단용)."""
import re, requests, io
import pandas as pd
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
def get(url):
    r = requests.get(url, headers=UA, timeout=30); print(f"\n##### {url} -> {r.status_code}"); return r.text
for url in ("https://www.trendforce.com/price", "https://www.trendforce.com/price/flash/flash_spot"):
    t = get(url)
    for m in re.finditer(r"Last Update\s*([\d-]+ [\d:]+)", t): print("  last update:", m.group(1))
    try:
        tbs = pd.read_html(io.StringIO(t))
        print("  tables:", len(tbs))
        for i, tb in enumerate(tbs):
            print(f"  [{i}] cols={list(tb.columns)[:9]} rows={len(tb)}")
            print("      " + " || ".join(str(list(r))[:160] for r in tb.head(3).values.tolist()))
    except Exception as e:
        print("  read_html", e)
t = get("https://www.trendforce.com/presscenter/news")
links = sorted(set(re.findall(r"href=\"(https?://www\.trendforce\.com/presscenter/news/[^\"]+)\"", t)))
print("  press links:", len(links)); print("\n".join(links[:15]))
titles = re.findall(r"<a[^>]+href=\"(https?://www\.trendforce\.com/presscenter/news/\d+[^\"]*)\"[^>]*>(.*?)</a>", t, re.S)
print("  with titles:", len(titles)); [print("   ", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", b))[:100], "|", a) for a, b in titles[:12]]
for url in ("https://www.trendforce.com/presscenter/news/search?keyword=DRAM", "https://www.trendforce.com/presscenter/news?keyword=DRAM", "https://www.trendforce.com/presscenter/news/page/2", "https://www.trendforce.com/news/category/insights"):
    try:
        t = get(url); print("  links:", len(set(re.findall(r"presscenter/news/\d+", t))), "news links:", len(set(re.findall(r"trendforce.com/news/20\d\d/\d\d/\d\d/[^\"]+", t))))
    except Exception as e: print(url, e)
t = get("https://www.trendforce.com/news/category/memory") if False else ""
