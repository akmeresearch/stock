"""DART 고유번호(corp_code)를 watchlist.json의 국내 종목에 채운다.

DART Open API의 corpCode.xml(zip)을 받아 종목코드 → corp_code 매핑을 만든 뒤,
data/watchlist.json 의 dart_corp_code 가 비어 있는 항목을 채운다.
환경변수 DART_API_KEY 필요.
"""
import io
import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST = ROOT / "data" / "watchlist.json"
CORP_URL = "https://opendart.fss.or.kr/api/corpCode.xml"


def fetch_corp_map(api_key: str) -> dict[str, str]:
    r = requests.get(CORP_URL, params={"crtfc_key": api_key}, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_bytes)
    mapping = {}
    for item in root.iter("list"):
        stock = (item.findtext("stock_code") or "").strip()
        corp = (item.findtext("corp_code") or "").strip()
        if stock and corp:
            mapping[stock] = corp
    return mapping


def main() -> int:
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        print("DART_API_KEY not set", file=sys.stderr)
        return 1

    wl = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    missing = [s for s in wl.get("kr", []) if not s.get("dart_corp_code")]
    if not missing:
        print("all corp codes present")
        return 0

    corp_map = fetch_corp_map(api_key)
    print(f"corpCode list loaded: {len(corp_map):,} listed companies")

    filled = 0
    for s in missing:
        code = corp_map.get(s["ticker"])
        if code:
            s["dart_corp_code"] = code
            filled += 1
            print(f"  {s['name']} ({s['ticker']}) -> {code}")
        else:
            print(f"  {s['name']} ({s['ticker']}) -> NOT FOUND", file=sys.stderr)

    WATCHLIST.write_text(json.dumps(wl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"filled {filled}/{len(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
