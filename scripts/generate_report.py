"""실적 분석 리포트 생성.

입력: 종목코드, 분기, 원문 파일(들) 또는 DART 접수번호
처리: prompts/earnings_analysis.md 를 system prompt로, 원문을 user 메시지로 Claude API 호출
출력: data/reports/{ticker}_{period}.md

사용 예
  python scripts/generate_report.py --ticker 005930 --period 2026Q3 \
      --source ir.txt --source concall.txt --consensus "영업이익 105.4조" \
      --price "206,750원 / 시총 1,208.7조 / PER 9.27 (2026-11-05)"

  python scripts/generate_report.py --ticker 005930 --period 2026Q3 --rcept 20261029000123 \
      --url https://news.samsung.com/kr/... --url https://www.thelec.kr/...
      (DART 접수번호 + IR 보도자료·컨콜 전문 URL을 함께 분석. 공시만 넣으면 숫자 6개뿐이라 부문별·가이던스가 비게 된다)

환경변수: ANTHROPIC_API_KEY (필수), DART_API_KEY (--rcept 사용 시)
"""
import argparse
import io
import json
import os
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
PROMPT = ROOT / "prompts" / "earnings_analysis.md"
WATCHLIST = ROOT / "data" / "watchlist.json"
REPORTS = ROOT / "data" / "reports"

MODEL = os.environ.get("REPORT_MODEL", "claude-sonnet-5-5")
MAX_INPUT_CHARS = 180_000  # 원문이 너무 길면 앞부분만 (약 6만 토큰)


def load_watchlist_entry(ticker: str) -> dict:
    wl = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    for s in wl.get("kr", []) + wl.get("us", []):
        if s["ticker"] == ticker:
            return s
    return {"ticker": ticker, "name": ticker}


SECTION_KEYS = ("사업의 내용", "경영진단", "재무에 관한 사항", "연결재무제표", "요약재무정보", "영업실적")


def trim_dart_text(text: str, limit: int = MAX_INPUT_CHARS) -> str:
    """분기보고서처럼 긴 문서는 실적 관련 섹션 주변을 우선 남긴다."""
    if len(text) <= limit:
        return text
    head = text[:20_000]  # 표지·요약
    slots = []
    for key in SECTION_KEYS:
        for m in re.finditer(re.escape(key), text):
            slots.append(m.start())
    slots = sorted(set(slots))
    chunks, used = [], 0
    per = max(20_000, (limit - len(head)) // max(1, min(len(slots), 6)))
    last_end = 0
    for pos in slots:
        if pos < last_end:
            continue
        chunk = text[pos:pos + per]
        chunks.append(chunk)
        used += len(chunk)
        last_end = pos + per
        if used >= limit - len(head):
            break
    body = "\n\n[...중략...]\n\n".join(chunks) if chunks else text[20_000:limit]
    return (head + "\n\n[...중략...]\n\n" + body)[:limit]


def fetch_dart_document(rcept_no: str, api_key: str) -> str:
    """DART 공시 원문(zip 안의 xml)을 받아 태그를 벗긴 텍스트로 반환."""
    r = requests.get(
        "https://opendart.fss.or.kr/api/document.xml",
        params={"crtfc_key": api_key, "rcept_no": rcept_no},
        timeout=60,
    )
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".xml", ".html", ".htm"))]
        raw = zf.read(names[0]).decode("utf-8", errors="ignore")
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text)
    return trim_dart_text(text.strip())


def fetch_url_text(url: str) -> str:
    """웹페이지 본문을 텍스트로. 후보 블록 중 텍스트가 가장 긴 것을 본문으로 본다."""
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript", "iframe"]):
        tag.decompose()

    def clean(node) -> str:
        lines = [ln.strip() for ln in node.get_text("\n").splitlines()]
        return "\n".join(ln for ln in lines if ln)

    candidates = soup.find_all(["article", "section", "div"], id=re.compile("article|content|body|view|news", re.I))
    candidates += soup.find_all(["article", "section", "div"], class_=re.compile("article|content|body|view|news", re.I))
    candidates += soup.find_all("article")
    best = max((clean(c) for c in candidates), key=len, default="")
    fallback = clean(soup.body or soup)
    # 후보 본문이 전체의 절반도 안 되면 추출이 잘못된 것이므로 전체를 쓴다
    return best if len(best) >= len(fallback) * 0.5 and len(best) > 500 else fallback


def build_user_message(entry: dict, period: str, sources: list[tuple[str, str]],
                       consensus: str | None, price: str | None) -> str:
    parts = [
        f"기업명: {entry.get('name')}",
        f"종목코드: {entry.get('ticker')}",
        f"대상 분기: {period}",
        f"컨센서스: {consensus or '미제공'}",
        f"현재가/시총/PER: {price or '미제공'}",
        "",
    ]
    for label, body in sources:
        parts.append(f"=== 자료: {label} ===")
        parts.append(body[:MAX_INPUT_CHARS])
        parts.append("")
    parts.append("위 자료만 근거로 스킬 지침의 출력 형식에 맞춰 리포트를 작성하라.")
    return "\n".join(parts)


def call_claude(system: str, user: str) -> tuple[str, dict]:
    """Claude 호출. 출력이 max_tokens에 걸리면 '이어서'를 요청해 최대 3회까지 이어 붙인다."""
    from anthropic import Anthropic

    client = Anthropic()
    messages = [{"role": "user", "content": user}]
    body, meta = "", {"stop": [], "in": 0, "out": 0}
    for _ in range(3):
        resp = client.messages.create(model=MODEL, max_tokens=16000, system=system, messages=messages)
        chunk = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        body += chunk
        meta["stop"].append(resp.stop_reason)
        meta["in"] += resp.usage.input_tokens
        meta["out"] += resp.usage.output_tokens
        print(f"stop_reason={resp.stop_reason} in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
        if resp.stop_reason != "max_tokens":
            break
        messages += [
            {"role": "assistant", "content": chunk},
            {"role": "user", "content": "출력이 잘렸다. 마지막 문장 바로 다음부터 이어서, 반복 없이 끝까지 작성하라."},
        ]
    return body, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--period", required=True, help="예: 2026Q3")
    ap.add_argument("--source", action="append", default=[], help="원문 텍스트 파일 (여러 번 가능)")
    ap.add_argument("--rcept", help="DART 접수번호 (원문을 직접 내려받음)")
    ap.add_argument("--url", action="append", default=[], help="IR 보도자료·컨콜 전문 등 웹페이지 (여러 번 가능)")
    ap.add_argument("--kind", default="", help="공시 종류 (잠정실적/분기보고서 등) — frontmatter 기록용")
    ap.add_argument("--consensus")
    ap.add_argument("--price")
    ap.add_argument("--dry-run", action="store_true", help="API 호출 없이 프롬프트만 출력")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY") and not args.dry_run:
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    entry = load_watchlist_entry(args.ticker)
    sources: list[tuple[str, str]] = []
    for p in args.source:
        path = Path(p)
        sources.append((path.name, path.read_text(encoding="utf-8", errors="ignore")))
    if args.rcept:
        key = os.environ.get("DART_API_KEY", "")
        if not key:
            print("DART_API_KEY not set", file=sys.stderr)
            return 1
        sources.append((f"DART {args.rcept}", fetch_dart_document(args.rcept, key)))
    for u in [x.strip() for x in args.url if x.strip()]:
        try:
            sources.append((u, fetch_url_text(u)))
        except Exception as e:  # 한 URL 실패가 전체를 막지 않도록
            print(f"skip url {u}: {e}", file=sys.stderr)
    if not sources:
        print("no sources: use --source, --rcept or --url", file=sys.stderr)
        return 1

    system = PROMPT.read_text(encoding="utf-8")
    user = build_user_message(entry, args.period, sources, args.consensus, args.price)

    if args.dry_run:
        print(user[:3000])
        print(f"\n... total {len(user):,} chars")
        return 0

    body, meta = call_claude(system, user)

    front = (
        "---\n"
        f'ticker: "{entry.get("ticker")}"\n'
        f"name: {entry.get('name')}\n"
        f"period: {args.period}\n"
        f"published: {date.today().isoformat()}\n"
        f"model: {MODEL}\n"
        "source_type: auto\n"
        f"filing_kind: {args.kind}\n"
        f"stop_reason: {','.join(meta['stop'])}\n"
        f"tokens_in: {meta['in']}\n"
        f"tokens_out: {meta['out']}\n"
        "---\n\n"
    )
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{entry.get('ticker')}_{args.period}.md"
    out.write_text(front + body.strip() + "\n", encoding="utf-8")
    print(f"written: {out.relative_to(ROOT)} ({len(body):,} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
