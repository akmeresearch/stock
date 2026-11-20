"""메모리 가격 소스 탐색 (진단용)."""
import re, requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
def show(url, n=1500, pat=None):
    try:
        r = requests.get(url, headers=UA, timeout=30)
        t = r.text
        print(f"\n##### {url} -> {r.status_code}, {len(t):,} chars")
        if pat:
            for m in list(re.finditer(pat, t))[:12]:
                print("   match:", t[max(0, m.start()-100): m.start()+300].replace("\n", " ")[:400])
        else:
            body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
            body = re.sub(r"<[^>]+>", " ", body); body = re.sub(r"\s+", " ", body)
            i = body.find("DDR5"); print(body[max(0, i-300): i+n] if i > 0 else body[:n])
    except Exception as e:
        print(f"\n##### {url} ERR {e}")
show("https://www.trendforce.com/price")
show("https://www.trendforce.com/price", pat=r"pricedetail|/api/|chart|history")
show("https://www.trendforce.com/pricedetail/dram/dram_spot", n=2500)
show("https://www.trendforce.com/pricedetail/dram/dram_spot", pat=r"<script[^>]*src=\"[^\"]+\"|series|labels|\"data\"")
show("https://www.trendforce.com/price/flash/flash_spot", n=2000)
show("https://www.trendforce.com/price/flash", n=2000)
show("https://www.trendforce.com/pricedetail/flash/flash_spot", n=2000)
show("https://www.dramexchange.com/", n=2000)
show("https://www.trendforce.com/presscenter/news", n=3000)
show("https://www.trendforce.com/presscenter/news", pat=r"href=\"(https://www.trendforce.com/presscenter/news/\d{8}-\d+\.html)\"")
show("https://www.trendforce.com/rss", n=800)
show("https://newsletter.semianalysis.com/feed", n=1500)
show("https://www.semianalysis.com/feed", n=1500)
