"""수집 스크립트 공통 유틸."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Accept": "application/json,text/csv,text/html,*/*",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y%m%d")


def get_json(url: str, timeout: int = 15, **kw):
    r = requests.get(url, headers=HEADERS, timeout=timeout, **kw)
    r.raise_for_status()
    return r.json()


def get_text(url: str, timeout: int = 15, **kw) -> str:
    r = requests.get(url, headers=HEADERS, timeout=timeout, **kw)
    r.raise_for_status()
    return r.text


def num(v):
    """'1,234.5' → 1234.5, 빈 값·비숫자 → None."""
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f == f else None  # NaN 제거


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def keep_previous(new_item: dict, old_item: dict | None, ok_statuses=("ok", "stale")) -> dict:
    """새 수집이 실패했고 이전 값이 있으면 이전 값을 stale 로 유지."""
    if new_item.get("status") == "ok":
        return new_item
    if old_item and old_item.get("status") in ok_statuses:
        return {**old_item, "status": "stale", "errorAt": now_iso()}
    return new_item
