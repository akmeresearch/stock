"""data/reports/*.md 의 frontmatter를 읽어 data/reports/index.json 을 만든다. 화면이 이 파일로 목록을 그린다."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "data" / "reports"


def parse(md_path: Path) -> dict | None:
    text = md_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"')
    body = m.group(2)
    title = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), md_path.stem)
    summary = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("> ")), "")
    return {
        "file": md_path.name,
        "ticker": meta.get("ticker", ""),
        "name": meta.get("name", ""),
        "period": meta.get("period", ""),
        "published": meta.get("published", ""),
        "source_type": meta.get("source_type", ""),
        "title": title,
        "summary": summary,
    }


def main() -> None:
    items = [r for p in sorted(REPORTS.glob("*.md")) if (r := parse(p))]
    items.sort(key=lambda r: (r["published"], r["period"]), reverse=True)
    (REPORTS / "index.json").write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"index.json: {len(items)} reports")


if __name__ == "__main__":
    main()
