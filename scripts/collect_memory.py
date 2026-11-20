"""메모리 가격 수집 (TrendForce / DRAMeXchange 공개 페이지) → data/memory_prices.json

 - 매일: trendforce.com/price (DRAM 현물·계약·모듈·GDDR), /price/flash/flash_spot (NAND 현물·계약·웨이퍼·SSD) 표를 읽어
   품목별 세션 평균가를 날짜별 히스토리에 쌓는다 (하루 1점, 같은 날 재수집 시 덮어씀).
 - --backfill: TrendForce 주간 '[Insights] Memory Spot Price Update' 기사에서 DDR4 8Gb 평균가·512Gb TLC 웨이퍼 평균가를 뽑아
   과거 히스토리를 채운다 (주 1점, 'weekly' 표시).

실행: python scripts/collect_memory.py [--backfill]
"""
import argparse
import io
import json
import re
import sys
from datetime import date, datetime

import pandas as pd
import requests

from common import DATA, now_iso

OUT = DATA / "memory_prices.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
PAGES = [("https://www.trendforce.com/price", "dram"), ("https://www.trendforce.com/price/flash/flash_spot", "nand")]

# 표를 품목명으로 그룹 식별: (그룹 id, 표시명, 품목 매칭 정규식, 표 종류)
GROUPS = [
    ("dram_spot", "DRAM 현물", r"^DDR[345] \d+Gb", "spot"),
    ("dram_contract", "DRAM 계약 (반월)", r"SO-DIMM|^DDR[34] \d+Gb .*x(8|16)$", "contract"),
    ("module_spot", "DRAM 모듈 현물", r"DIMM \d+GB", "spot"),
    ("gddr_spot", "GDDR 현물", r"^GDDR", "spot"),
    ("nand_spot", "NAND 현물 (칩)", r"^(SLC|MLC) \d+Gb", "spot"),
    ("nand_contract", "NAND 계약 (반월)", r"^NAND \d+Gb", "contract"),
    ("wafer_spot", "NAND 웨이퍼 현물", r"^\d+Gb TLC$", "spot"),
    ("ssd_contract", "PC OEM SSD 계약", r"mSATA|M\.2|PCIe", "contract"),
]
# 페이지에 표시되는 핵심 품목 (사이트 카드 순서)
KEY_ITEMS = ["DDR5 16Gb (2Gx8) 4800/5600", "DDR4 8Gb (1Gx8) 3200", "DDR4 16Gb (2Gx8) 3200", "512Gb TLC", "DDR5 RDIMM 32GB 4800/5600", "GDDR6 8Gb"]


def pct(s) -> float | None:
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", str(s))
    return float(m.group(1)) if m else None


def numf(v) -> float | None:
    try:
        f = float(str(v).replace(",", "")); return f
    except ValueError:
        return None


def classify(item: str, cols: list[str]) -> tuple[str, str] | None:
    for gid, label, pat, kind in GROUPS:
        if re.search(pat, item):
            # 'DDR4 16Gb 2Gx8'(계약) 과 'DDR4 16Gb (2Gx8) 3200'(현물) 구분: 현물 표는 Daily/Weekly High 열이 있다
            is_spot = any(c in cols for c in ("Daily High", "Weekly High"))
            if kind == "spot" and not is_spot and gid.startswith("dram"):
                continue
            if kind == "contract" and is_spot:
                continue
            return gid, label
    return None


def parse_page(html: str) -> list[dict]:
    """[{item, group, label, avg, change, high, low}]"""
    rows = []
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception as e:
        print(f"  read_html: {e}", file=sys.stderr); return rows
    for tb in tables:
        cols = [str(c) for c in tb.columns]
        if "Item" not in cols:
            continue
        for _, r in tb.iterrows():
            item = str(r["Item"]).strip()
            if not item or item == "nan" or "click here" in item:
                continue
            g = classify(item, cols)
            if not g:
                continue
            avg = numf(r.get("Session Average", r.get("Average")))
            if avg is None:
                continue
            chg = pct(r.get("Session Change", r.get("Average Change", r.get("Change", ""))))
            high = numf(r.get("Session High", r.get("High"))); low = numf(r.get("Session Low", r.get("Low")))
            rows.append({"item": item, "group": g[0], "label": g[1], "avg": avg, "change": chg, "high": high, "low": low})
    return rows


def session_dates(html: str) -> list[str]:
    return re.findall(r"Last Update\s*([\d-]+ [\d:]+)", html)


def load() -> dict:
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"items": {}, "groups": {}, "sessions": {}}


def save(d: dict):
    d["updatedAt"] = now_iso()
    d["groups"] = {gid: label for gid, label, _, _ in GROUPS}
    d["keyItems"] = KEY_ITEMS
    OUT.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def add_point(d: dict, item: str, group: str, label: str, day: str, avg: float, chg, high=None, low=None, src="daily"):
    it = d["items"].setdefault(item, {"group": group, "label": label, "unit": "USD", "history": []})
    it["group"], it["label"] = group, label
    hist = it["history"]
    # 같은 날짜면 덮어쓰기 (daily 가 weekly 보다 우선)
    for i, h in enumerate(hist):
        if h[0] == day:
            if src == "weekly" and (len(h) < 5 or h[4] != "weekly"):
                return
            hist[i] = [day, avg, chg, [high, low], src]; return
    hist.append([day, avg, chg, [high, low], src]); hist.sort(key=lambda h: h[0])


def collect_today(d: dict) -> int:
    n = 0
    for url, tag in PAGES:
        try:
            html = requests.get(url, headers=UA, timeout=40).text
        except Exception as e:
            print(f"  {url}: {e}", file=sys.stderr); continue
        dates = session_dates(html)
        print(f"  {tag}: sessions {dates}")
        rows = parse_page(html)
        print(f"  {tag}: {len(rows)} rows")
        # 날짜: 표마다 다르지만 품목 그룹별로 Last Update 를 매핑하기 어려우므로 '수집일' 기준 + 최신 세션 시각 기록
        today = date.today().isoformat()
        for r in rows:
            add_point(d, r["item"], r["group"], r["label"], today, r["avg"], r["change"], r["high"], r["low"])
            n += 1
        d["sessions"][tag] = {"fetchedAt": now_iso(), "lastUpdate": dates}
    return n


# ------------------------------------------------------------------ 주간 기사 백필
SEED = [  # 검색으로 확인한 주간 기사 (목록 페이지를 못 읽을 때의 시드)
    "https://www.trendforce.com/news/2025/03/19/insights-memory-spot-price-update-ddr4-ddr3-prices-rise-amid-strong-ddr5-rebound-led-by-sk-hynix/",
    "https://www.trendforce.com/news/2025/06/11/insights-memory-spot-price-update-ddr4-and-ddr5-chips-hit-price-parity-in-early-june-amid-soaring-hikes/",
    "https://www.trendforce.com/news/2025/07/16/insights-memory-spot-price-update-prices-slightly-cool-off-after-recent-surge-with-ddr4-leading-the-drop",
    "https://www.trendforce.com/news/2025/08/13/insights-memory-spot-price-update-ddr4-price-surge-slows-amid-samsung-eol-delay-rumors/",
    "https://www.trendforce.com/news/2025/09/03/insights-memory-spot-price-update-ddr4-prices-outpace-ddr5-as-memory-giants-eol-impact-lingers/",
    "https://www.trendforce.com/news/2025/09/10/insights-memory-spot-price-update-sandisks-10-price-hike-meets-demand-side-resistance/",
    "https://www.trendforce.com/news/2025/09/17/insights-memory-spot-price-update-ddr4-spot-prices-surge-amid-tight-supply-buyers-struggle-to-keep-pace/",
    "https://www.trendforce.com/news/2025/10/15/insights-memory-spot-price-update-dram-module-sellers-mostly-halt-quotes-as-mainstream-ddr4-soars-7-21/",
    "https://www.trendforce.com/news/2025/10/22/insights-memory-spot-price-update-ddr4-ddr5-trading-surges-as-buyers-hedge-price-risks-mainstream-ddr4-up-9/",
    "https://www.trendforce.com/news/2025/11/05/insights-memory-spot-price-update-dram-buyers-rush-in-as-ddr5-spot-prices-jump-30-amid-tight-supply/",
    "https://www.trendforce.com/news/2025/11/12/insights-memory-spot-price-update-dram-chip-prices-surpass-module-prices-signaling-imminent-surge/",
    "https://www.trendforce.com/news/2025/11/19/insights-memory-spot-price-update-ddr5-prices-up-307-since-september-as-module-costs-poised-to-surge/",
    "https://www.trendforce.com/news/2025/12/03/insights-memory-spot-price-update-ddr4-stays-above-ddr5-as-spot-prices-show-no-sign-of-letup/",
    "https://www.trendforce.com/news/2025/12/10/insights-memory-spot-price-update-ddr4-rally-strengthens-on-16gb-gains-ddr5-ddr3-see-mild-pullbacks/",
    "https://www.trendforce.com/news/2025/12/24/insights-memory-spot-price-update-kingston-leads-dram-price-surge-as-ddr4-ddr5-and-modules-hold-strong/",
    "https://www.trendforce.com/news/2025/12/31/insights-memory-spot-price-update-ddr4-spot-prices-climb-as-samsung-holds-eol-line",
    "https://www.trendforce.com/news/2026/01/14/insights-memory-spot-price-update-dram-surges-as-sellers-hold-back-inventory-mainstream-ddr4-up-nearly-10/",
    "https://www.trendforce.com/news/2026/01/28/insights-memory-spot-price-update-ddr4ddr5-hit-highs-buyers-hesitant-ddr3-sees-uptick/",
    "https://www.trendforce.com/news/2026/02/04/insights-memory-spot-price-update-dram-stalls-ahead-of-late-feb-contract-price-settlements/",
    "https://www.trendforce.com/news/2026/03/04/insights-memory-spot-price-update-dram-spots-top-contracts-sentiment-cautious-ahead-of-q2-negotiations/",
    "https://www.trendforce.com/news/2026/03/25/insights-memory-spot-price-update-dram-spot-momentum-constrained-as-march-contracts-hold-ddr4-weakest/",
    "https://www.trendforce.com/news/2026/04/01/insights-memory-spot-price-update-ddr3-strength-contrasts-weak-ddr4-and-ddr5-amid-high-prices-and-soft-demand/",
    "https://www.trendforce.com/news/2026/04/08/insights-memory-spot-price-update-dram-extends-gradual-downtrend-on-contained-selling-pressure-ddr4-drops-1-18/",
    "https://www.trendforce.com/news/2026/04/15/insights-memory-spot-price-update-dram-spot-sellers-hold-firm-ahead-of-mid-april-pricing-ddr4-edges-lower-0-48/",
    "https://www.trendforce.com/news/2026/04/29/insights-memory-spot-price-update-ddr5-sees-sporadic-buying-interest-ddr4-price-cuts-fail-to-revive-demand/",
    "https://www.trendforce.com/news/2026/05/27/insights-memory-spot-price-update-ddr5-spot-price-gains-narrow-amid-sluggish-trading-ddr4-rebounds/",
    "https://www.trendforce.com/news/2026/07/22/insights-memory-spot-price-update-dram-spot-market-edges-higher-as-branded-ddr4-demand-supports-prices/",
    "https://www.trendforce.com/news/2026/09/23/insights-memory-spot-price-update-dram-spot-prices-hold-cautious-tone-ddr4-2gx8-drops-3-6/",
    "https://www.trendforce.com/news/2026/09/30/insights-memory-spot-price-update-dram-market-quiet-amid-holidays-nand-buying-stays-weak/",
    "https://www.trendforce.com/news/2026/11/04/insights-memory-spot-price-update-mainstream-ddr4-prices-dip-0-09-as-spot-premium-keeps-buyers-on-sidelines/",
    "https://www.trendforce.com/news/2026/11/18/insights-memory-spot-price-update-nand-spot-contract-price-gap-exceeds-20-amid-weak-demand/",
    "https://www.trendforce.com/news/2026/06/03/insights-memory-spot-price-update-ddr4-and-ddr5-extend-gains-though-higher-quotes-temper-procurement-demand/",
    "https://www.trendforce.com/news/2026/06/10/insights-memory-spot-price-update-ddr5-spot-momentum-continues-as-ddr4-tightness-spills-over-to-ddr3/",
    "https://www.trendforce.com/news/2026/06/17/insights-memory-spot-price-update-ddr3-strengthens-while-ddr4-faces-constraints-and-spec-downgrading",
    "https://www.trendforce.com/news/2026/07/08/insights-memory-spot-price-update-dram-spot-trading-remains-subdued-with-ddr3-and-4gb-ddr4-prices-edging-higher/",
    "https://www.trendforce.com/news/2026/07/29/insights-memory-spot-price-update-dram-spot-prices-rise-slightly-as-ddr3-ddr4-and-ddr5-inquiries-pick-up/",
    "https://www.trendforce.com/news/2026/08/05/insights-memory-spot-price-update-dram-spot-price-gains-slow-while-ddr4-and-ddr3-continue-uptrend/",
    "https://www.trendforce.com/news/2026/08/12/insights-memory-spot-price-update-dram-spot-trading-stays-subdued-as-pricing-gap-persists-ddr4-up-0-93/",
    "https://www.trendforce.com/news/2026/09/09/insights-memory-spot-price-update-ddr4-mainstream-prices-rise-1-78-on-2gx8-orders-ddr5-demand-remains-limited",
    "https://www.trendforce.com/news/2026/09/16/insights-memory-spot-price-update-dram-spot-cools-as-ddr5-inquiries-slow-2gx8-ddr4-prices-retreat",
    "https://www.trendforce.com/news/2026/10/21/insights-memory-spot-price-update-ddr5-supply-tight-ddr4-trading-subdued-despite-0-84-gain-in-mainstream-prices/",
]


def weekly_article_urls() -> list[str]:
    """시드 + 최근 뉴스 목록(/news/page/N, 페이지당 6건)에서 주간 Insights 기사 URL."""
    urls = set(SEED)
    for page in range(1, 60):
        try:
            t = requests.get(f"https://www.trendforce.com/news/page/{page}", headers=UA, timeout=30).text
        except Exception:
            break
        found = set(re.findall(r"https?://www\.trendforce\.com/news/20\d\d/\d\d/\d\d/insights-memory-spot-price-update[^\"'\s<]*", t))
        dates = re.findall(r"trendforce\.com/news/(20\d\d/\d\d/\d\d)/", t)
        urls |= found
        # 2주 이상 지난 페이지까지 가면 중단 (주간 기사는 시드로 커버)
        if dates and (date.today() - date.fromisoformat(min(dates).replace("/", "-"))).days > 21:
            break
    return sorted(urls)


def extract_weekly(url: str) -> list[tuple[str, str, float, float | None]]:
    """기사에서 (품목, 날짜, 평균가, 변동%) 추출. 날짜는 기사 URL 날짜."""
    t = requests.get(url, headers=UA, timeout=30).text
    m = re.search(r"/news/(20\d\d)/(\d\d)/(\d\d)/", url)
    day = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else date.today().isoformat()
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    body = re.sub(r"<[^>]+>", " ", body); body = re.sub(r"\s+", " ", body)
    out = []
    for m2 in re.finditer(r"US\$\s?(\d+(?:\.\d+)?)", body):
        ctx = body[max(0, m2.start() - 260): m2.start()]
        val = float(m2.group(1))
        chg = None
        mc = re.search(r"(-?\d+(?:\.\d+)?)\s*%", body[max(0, m2.start() - 80): m2.start() + 40])
        if mc:
            chg = float(mc.group(1))
            if re.search(r"(fell|declin|drop|down|decreas|lower|retreat|slid)", body[max(0, m2.start() - 120): m2.start()], re.I) and chg > 0:
                chg = -chg
        if re.search(r"512Gb", ctx) and re.search(r"wafer|TLC|NAND", ctx):
            out.append(("512Gb TLC", day, val, chg))
        elif re.search(r"DDR4", ctx) and re.search(r"1Gx8|8Gb|mainstream", ctx) and not re.search(r"16Gb|2Gx8", ctx[-120:]):
            out.append(("DDR4 8Gb (1Gx8) 3200", day, val, chg))
        elif re.search(r"DDR5 16Gb|DDR5", ctx[-120:]) and re.search(r"average|spot", ctx[-120:], re.I) and 20 < val < 200:
            out.append(("DDR5 16Gb (2Gx8) 4800/5600", day, val, chg))
    # 품목당 첫 값만
    seen, uniq = set(), []
    for o in out:
        if o[0] in seen:
            continue
        seen.add(o[0]); uniq.append(o)
    return uniq


def backfill(d: dict) -> int:
    done = set(d.get("backfilled", []))
    urls = [u for u in weekly_article_urls() if u not in done]
    print(f"  weekly articles: {len(urls)} new")
    n = 0
    for u in urls:
        try:
            pts = extract_weekly(u)
        except Exception as e:
            print(f"  {u[-60:]}: {e}", file=sys.stderr); continue
        for item, day, val, chg in pts:
            g = next(((gid, label) for gid, label, pat, _ in GROUPS if re.search(pat, item)), ("dram_spot", "DRAM 현물"))
            add_point(d, item, g[0], g[1], day, val, chg, src="weekly"); n += 1
        print(f"  {u.split('/')[-2][:50] if u.endswith('/') else u.split('/')[-1][:50]}: {[(p[0][:10], p[2]) for p in pts]}")
        done.add(u)
    d["backfilled"] = sorted(done)
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    args = ap.parse_args()
    d = load()
    n = collect_today(d)
    print(f"today: {n} points")
    if args.backfill:
        print(f"backfill: {backfill(d)} points")
    if not d["items"]:
        print("no data", file=sys.stderr); return 1
    save(d)
    print(f"saved {len(d['items'])} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
