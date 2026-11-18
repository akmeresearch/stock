"""상장법인을 투자자 관점의 산업 분류(대 → 중)로 매핑한다 → data/sector_map.json

 입력: data/listing.json (종목명·KRX 표준산업분류·주요제품)
 방법: Claude 에 60개씩 묶어 아래 TAXONOMY 중 하나를 고르게 한다. 분류 결과가 TAXONOMY 에 없으면 버리고 다음 실행에서 재시도.
 이미 분류된 종목은 건너뛴다 (--redo CODE,CODE 로 다시).

실행: python scripts/classify_sectors.py [--limit N] [--redo 005930,000660] [--workers 4]
환경변수: ANTHROPIC_API_KEY
"""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from common import DATA, load_json, now_iso

OUT = DATA / "sector_map.json"
MODEL = os.environ.get("SECTOR_MODEL", os.environ.get("REPORT_MODEL", "claude-sonnet-5-5"))
BATCH = 60

TAXONOMY = {
    "반도체": ["메모리반도체", "시스템반도체·팹리스", "반도체장비", "반도체소재", "반도체기판·부품", "후공정·테스트"],
    "IT하드웨어": ["디스플레이", "전자부품", "PCB", "스마트폰·가전", "통신장비", "컴퓨터·주변기기"],
    "배터리": ["배터리셀", "양극재·음극재", "배터리소재(분리막·전해액 등)", "배터리장비·부품"],
    "Auto": ["완성차", "자동차부품", "타이어"],
    "헬스케어": ["바이오_신약", "바이오_CMO", "제약", "의료기기", "진단", "헬스케어서비스·유통"],
    "인터넷·소프트웨어": ["플랫폼", "게임", "소프트웨어·SI", "보안", "AI·데이터"],
    "미디어·엔터": ["엔터테인먼트", "미디어·콘텐츠", "광고", "여행·레저"],
    "소비재": ["화장품", "의류·패션", "음식료", "유통", "가구·생활용품", "교육"],
    "기초소재": ["철강", "비철금속", "석유화학 대형사", "정밀화학·소재", "시멘트·건자재", "제지·포장"],
    "에너지·유틸리티": ["정유", "가스·유틸리티", "신재생에너지·태양광", "수소·연료전지", "원전"],
    "전력·기계": ["전력기기", "기계·공작기계", "로봇·자동화", "건설기계", "방산·항공우주"],
    "조선·운송": ["조선", "조선기자재", "해운", "항공", "육상운송·물류"],
    "건설·부동산": ["건설", "건축자재·인테리어", "부동산·리츠"],
    "금융": ["은행", "증권", "보험", "카드·캐피탈·기타금융"],
    "통신": ["통신서비스"],
    "지주·기타": ["지주회사", "기타서비스", "SPAC"],
}
VALID = {(l1, l2) for l1, v in TAXONOMY.items() for l2 in v}

SYSTEM = f"""너는 한국 주식 섹터 애널리스트다. 상장회사 목록을 받아 각 회사를 아래 분류표의 (산업대, 산업중) 한 쌍으로 분류한다.
분류표 (산업대: 산업중 목록):
{chr(10).join(f'- {k}: {", ".join(v)}' for k, v in TAXONOMY.items())}

규칙:
- 회사의 핵심 매출원 기준으로 고른다. 종목명·표준산업분류·주요제품을 함께 본다. 이름만으로 알 수 있는 유명 기업은 네가 아는 사업 내용을 우선한다.
- 반드시 분류표에 있는 조합만 쓴다. 애매하면 가장 가까운 것, 정말 모르겠으면 ("지주·기타","기타서비스").
- 기업인수목적회사(스팩)는 ("지주·기타","SPAC"). 'xx홀딩스'·'xx지주' 등 순수 지주회사는 ("지주·기타","지주회사").
- 출력은 JSON 하나만: {{"종목코드": ["산업대","산업중"], ...}}. 설명·코드블록 없이."""


def parse_json(txt: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip(), flags=re.M)
    t = re.sub(r",\s*([}\]])", r"\1", t)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def classify_batch(items: list[dict]) -> dict:
    try:
        return _classify(items)
    except Exception as e:
        print(f"  batch FAIL {e}", file=sys.stderr); return {}


def _classify(items: list[dict]) -> dict:
    from anthropic import Anthropic
    client = Anthropic()
    lines = [f"{x['code']} | {x['name']} | {x.get('sector', '')} | {x.get('products', '')}" for x in items]
    user = "종목코드 | 회사명 | 표준산업분류 | 주요제품\n" + "\n".join(lines)
    out = {}
    for attempt in range(2):
        resp = client.messages.create(model=MODEL, max_tokens=4000, system=SYSTEM, messages=[{"role": "user", "content": user}])
        j = parse_json("".join(b.text for b in resp.content if getattr(b, "type", "") == "text"))
        if isinstance(j, dict):
            for code, pair in j.items():
                if isinstance(pair, list) and len(pair) == 2 and (pair[0], pair[1]) in VALID:
                    out[str(code).zfill(6)] = {"l1": pair[0], "l2": pair[1]}
            if len(out) >= len(items) * 0.8:
                break
        print(f"  batch retry ({len(out)}/{len(items)})", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--redo", default="")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    listing = load_json(DATA / "listing.json", {}).get("items", [])
    cur = load_json(OUT, {"items": {}})
    done = cur.get("items", {})
    redo = {c.strip().zfill(6) for c in args.redo.split(",") if c.strip()}
    todo = [x for x in listing if not x.get("etf") and (x["code"] not in done or x["code"] in redo)]
    if args.limit:
        todo = todo[: args.limit]
    print(f"listed {len(listing)}, classified {len(done)}, todo {len(todo)}")
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    n_ok = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, res in enumerate(ex.map(classify_batch, batches), 1):
            done.update(res); n_ok += len(res)
            print(f"batch {i}/{len(batches)}: {len(res)} classified")
            OUT.write_text(json.dumps({"updatedAt": now_iso(), "taxonomy": TAXONOMY, "count": len(done), "items": done}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    # 상장폐지된 종목 정리
    codes = {x["code"] for x in listing}
    done = {k: v for k, v in done.items() if k in codes}
    OUT.write_text(json.dumps({"updatedAt": now_iso(), "taxonomy": TAXONOMY, "count": len(done), "items": done}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"done: +{n_ok}, total {len(done)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
