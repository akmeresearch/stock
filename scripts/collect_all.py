"""수집 스크립트를 순서대로 실행. 하나가 실패해도 나머지는 계속 돈다."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS = ["collect_market.py", "collect_indicators.py", "collect_sentiment.py"]


def main() -> int:
    failed = []
    for job in JOBS:
        print(f"\n=== {job} ===", flush=True)
        rc = subprocess.call([sys.executable, str(HERE / job)])
        if rc != 0:
            failed.append(job)
    print("\nfailed:", failed or "none")
    return 0  # 부분 실패는 커밋을 막지 않는다 (stale 유지 로직이 있음)


if __name__ == "__main__":
    sys.exit(main())
