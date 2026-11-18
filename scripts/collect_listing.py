"""전체 상장종목 목록 (종목 스크린 페이지용) → data/listing.json

 - 상장법인: KRX KIND 상장법인목록 다운로드 (코스피·코스닥, 업종·주요제품 포함)
 - ETF / ETN: 네이버 금융 ETF·ETN 목록 API  → etf: true (스크린 페이지에서 기본 클래스 P)
 - 실패한 소스가 있으면 이전 파일의 해당 부분을 유지한다.

실행: python scripts/collect_listing.py
"""
import io
import sys

import pandas as pd
import requests

from common import DATA, load_json, now_iso, save_json

OUT = DATA / "listing.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Referer": "https://finance.naver.com/"}
KIND = "https://kind.krx.co.kr/corpgeneral/corpList.do"


def kind_market(market: str) -> list[dict]:
    """KIND 상장법인목록: stockMkt=코스피, kosdaqMkt=코스닥. 응답은 EUC-KR HTML 표."""
    r = requests.post(KIND, data={"method": "download", "searchType": "13", "marketType": market}, headers=UA, timeout=60)
    r.raise_for_status()
    html = r.content.decode("euc-kr", errors="replace")
    df = pd.read_html(io.StringIO(html), header=0)[0]
    df = df.rename(columns={"회사명": "name", "종목코드": "code", "업종": "sector", "주요제품": "products", "상장일": "listed"})
    df["code"] = df["code"].astype(str).str.zfill(6)
    mk = "KOSPI" if market == "stockMkt" else "KOSDAQ"
    out = []
    for _, row in df.iterrows():
        out.append({"code": row["code"], "name": str(row["name"]).strip(), "market": mk,
                    "sector": "" if pd.isna(row.get("sector")) else str(row["sector"]).strip(),
                    "products": "" if pd.isna(row.get("products")) else str(row["products"]).strip()[:60],
                    "listed": "" if pd.isna(row.get("listed")) else str(row["listed"])[:10]})
    return out


def naver_etf() -> list[dict]:
    out = []
    for kind, url in (("ETF", "https://finance.naver.com/api/sise/etfItemList.nhn"), ("ETN", "https://finance.naver.com/api/sise/etnItemList.nhn")):
        try:
            j = requests.get(url, headers=UA, timeout=30).json()
            items = j.get("result", {}).get("etfItemList") or j.get("result", {}).get("etnItemList") or []
        except Exception as e:
            print(f"{kind} list FAIL {e}", file=sys.stderr); continue
        for it in items:
            out.append({"code": str(it["itemcode"]).zfill(6), "name": it["itemname"], "market": kind, "sector": kind,
                        "products": "", "listed": "", "etf": True})
        print(f"{kind}: {len(items)}")
    return out


def main() -> int:
    prev = load_json(OUT, {"items": []})
    prev_items = prev.get("items", [])
    items, failed = [], []
    for mk in ("stockMkt", "kosdaqMkt"):
        try:
            got = kind_market(mk); print(f"{mk}: {len(got)}"); items += got
        except Exception as e:
            print(f"{mk} FAIL {e}", file=sys.stderr); failed.append(mk)
            label = "KOSPI" if mk == "stockMkt" else "KOSDAQ"
            items += [x for x in prev_items if x.get("market") == label]
    etfs = naver_etf()
    if etfs:
        items += etfs
    else:
        failed.append("etf"); items += [x for x in prev_items if x.get("etf")]
    # 중복 제거 (ETF 가 상장법인에 겹치는 일은 없지만 안전하게)
    seen, uniq = set(), []
    for x in items:
        if x["code"] in seen:
            continue
        seen.add(x["code"]); uniq.append(x)
    uniq.sort(key=lambda x: (x.get("etf", False), x["name"]))
    if not uniq:
        print("no items", file=sys.stderr); return 1
    save_json(OUT, {"updatedAt": now_iso(), "count": len(uniq), "failed": failed, "items": uniq})
    print(f"saved {len(uniq)} items (failed: {failed or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
