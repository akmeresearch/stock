import re, requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
def hrefs(url, pat):
    try:
        t = requests.get(url, headers=UA, timeout=30).text
    except Exception as e:
        print(url, "ERR", e); return
    hs = sorted(set(re.findall(pat, t)))
    print(f"\n##### {url} -> {len(t):,} chars, {len(hs)} links"); print("\n".join(hs[:25]))
    m = re.search(r"<title>(.*?)</title>", t, re.S); print("  title:", m.group(1).strip()[:100] if m else None)
    m = re.search(r"og:title\" content=\"([^\"]+)\"", t); print("  og:title:", m.group(1)[:100] if m else None)
hrefs("https://www.trendforce.com/presscenter/news", r"href=\"([^\"]*presscenter/news/[^\"]+)\"")
hrefs("https://www.trendforce.com/presscenter/news?keyword=DRAM", r"href=\"([^\"]*presscenter/news/[^\"]+)\"")
hrefs("https://www.trendforce.com/presscenter/news?keyword=DRAM&page=2", r"href=\"([^\"]*presscenter/news/[^\"]+)\"")
hrefs("https://www.trendforce.com/presscenter/news?keyword=DRAM&p=2", r"href=\"([^\"]*presscenter/news/[^\"]+)\"")
hrefs("https://www.trendforce.com/presscenter/news?keyword=DRAM&page_no=2", r"href=\"([^\"]*presscenter/news/[^\"]+)\"")
hrefs("https://www.trendforce.com/presscenter/news/semiconductor", r"href=\"([^\"]*presscenter/news/[^\"]+)\"")
hrefs("https://www.trendforce.com/news", r"href=\"([^\"]*trendforce\.com/news/20\d\d/[^\"]+)\"")
hrefs("https://www.trendforce.com/news?keyword=spot+price", r"href=\"([^\"]*trendforce\.com/news/20\d\d/[^\"]+)\"")
hrefs("https://www.trendforce.com/news?keyword=spot+price&page=2", r"href=\"([^\"]*trendforce\.com/news/20\d\d/[^\"]+)\"")
hrefs("https://www.trendforce.com/news/page/2", r"href=\"([^\"]*trendforce\.com/news/20\d\d/[^\"]+)\"")
hrefs("https://www.trendforce.com/news/semiconductors", r"href=\"([^\"]*trendforce\.com/news/20\d\d/[^\"]+)\"")
hrefs("https://www.trendforce.com/news/semiconductors/page/2", r"href=\"([^\"]*trendforce\.com/news/20\d\d/[^\"]+)\"")
hrefs("https://www.trendforce.com/presscenter/news/20261119-12857.html", r"href=\"([^\"]*presscenter/news/[^\"]+)\"")
