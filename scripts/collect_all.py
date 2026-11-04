"""모든 수집 스크립트를 순서대로 실행. 2단계에서 각 모듈을 채운다."""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KST = timezone(timedelta(hours=9))


def main():
    watchlist = json.loads((DATA / "watchlist.json").read_text(encoding="utf-8"))
    status = {
        "run_at": datetime.now(KST).isoformat(timespec="seconds"),
        "kr_count": len(watchlist.get("kr", [])),
        "us_count": len(watchlist.get("us", [])),
        "modules": ["prices", "flows", "financials", "macro"],
        "note": "placeholder — 수집 모듈은 2단계에서 구현",
    }
    (DATA / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print("status written:", status["run_at"])


if __name__ == "__main__":
    main()
