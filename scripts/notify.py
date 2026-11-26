"""텔레그램 알림.

사용
  python scripts/notify.py --setup            # 봇이 받은 메시지에서 chat_id 찾아 data/notify.json 에 저장 + 테스트 메시지
  python scripts/notify.py --text "메시지"      # 단발 발송
  python scripts/notify.py --reports           # data/reports 중 아직 알리지 않은 리포트 알림 (워크플로에서 호출)
  python scripts/notify.py --weekly            # 최신 위클리 알림
  python scripts/notify.py --daily             # 아직 알리지 않은 데일리 알림
환경변수: TELEGRAM_BOT_TOKEN. chat_id 는 data/notify.json 에 저장 (비밀 아님).
"""
import argparse
import json
import os
import sys

import requests

from common import DATA, load_json, now_iso, save_json

SITE = "https://akmeresearch.github.io/stock/"
STATE = DATA / "notify.json"


def api(token: str, method: str, **payload):
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=20)
    r.raise_for_status()
    out = r.json()
    if not out.get("ok"):
        raise RuntimeError(out.get("description"))
    return out["result"]


def targets(state: dict | None = None) -> list:
    """알림 받을 chat id 목록: chat_ids(여러 명) + chat_id(기존 1명)."""
    st = state if state is not None else load_json(STATE, {})
    ids = [c["id"] if isinstance(c, dict) else c for c in st.get("chat_ids", [])]
    if st.get("chat_id") and st["chat_id"] not in ids:
        ids.insert(0, st["chat_id"])
    return ids


def send(token: str, chat_id, text: str) -> None:
    """chat_id 하나를 받지만 실제로는 등록된 모든 수신자에게 보낸다 (chat_id 가 목록에 없으면 추가로)."""
    ids = targets()
    if chat_id and chat_id not in ids:
        ids.append(chat_id)
    for cid in ids:
        try:
            api(token, "sendMessage", chat_id=cid, text=text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            print(f"  telegram {cid}: {e}", file=sys.stderr)


def setup(token: str) -> int:
    """봇에게 말을 건 모든 대화(개인·그룹·채널)를 수신자 목록에 추가한다. 기존 수신자는 지우지 않는다."""
    updates = api(token, "getUpdates")
    chats = {}
    for u in updates:
        m = u.get("message") or u.get("edited_message") or u.get("channel_post") or u.get("edited_channel_post") or {}
        c = m.get("chat") or (u.get("my_chat_member") or {}).get("chat") or {}
        if c.get("id"):
            chats[c["id"]] = (c.get("title") or " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) or c.get("username") or "") + f" [{c.get('type', '')}]"
    state = load_json(STATE, {})
    cur = {(c["id"] if isinstance(c, dict) else c): (c.get("name", "") if isinstance(c, dict) else "") for c in state.get("chat_ids", [])}
    if state.get("chat_id"):
        cur.setdefault(state["chat_id"], state.get("chat_name", ""))
    added = [cid for cid in chats if cid not in cur]
    for cid in chats:
        cur[cid] = chats[cid]
    if not cur:
        print("봇이 받은 메시지가 없습니다. 텔레그램에서 봇 대화방을 열고 /start 를 보낸 뒤 다시 실행하세요.", file=sys.stderr)
        return 1
    state["chat_ids"] = [{"id": cid, "name": name} for cid, name in cur.items()]
    state.setdefault("chat_id", list(cur)[0]); state["setupAt"] = now_iso()
    state.setdefault("notified_reports", []); state.setdefault("notified_weekly", [])
    save_json(STATE, state)
    for cid in added:
        try:
            api(token, "sendMessage", chat_id=cid, text=f"✅ <b>AKME Research 알림 연결 완료</b>\n실적 리포트·데일리·위클리·딜 알림·공지 감시가 여기로 옵니다.\n{SITE}", parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            print(f"  welcome {cid}: {e}", file=sys.stderr)
    print("수신자:", ", ".join(f"{cid} {name}" for cid, name in cur.items()), f"| 새로 추가 {len(added)}")
    return 0


def notify_reports(token: str) -> int:
    state = load_json(STATE, {})
    chat_id = state.get("chat_id")
    if not chat_id:
        print("chat_id 없음 — --setup 먼저", file=sys.stderr)
        return 0
    done = set(state.get("notified_reports", []))
    idx = load_json(DATA / "reports" / "index.json", [])
    new = [r for r in idx if r["file"] not in done]
    for r in sorted(new, key=lambda x: x["published"]):
        kind = "자동 생성" if r.get("source_type") == "auto" else r.get("source_type", "")
        text = (f"📄 <b>{r['name']} {r['period']} 실적 리뷰</b> <i>({kind})</i>\n"
                f"{r['summary']}\n\n"
                f"<a href=\"{SITE}report.html?f={r['file']}\">리포트 열기</a> · <a href=\"{SITE}stock.html?code={r['ticker']}\">종목 페이지</a>")
        send(token, chat_id, text)
        done.add(r["file"])
        print("notified:", r["file"])
    state["notified_reports"] = sorted(done)
    save_json(STATE, state)
    return 0


def notify_weekly(token: str) -> int:
    state = load_json(STATE, {})
    chat_id = state.get("chat_id")
    if not chat_id:
        return 0
    done = set(state.get("notified_weekly", []))
    idx = load_json(DATA / "weekly" / "index.json", [])
    for w in sorted(idx, key=lambda x: x["week_end"]):
        key = f"{w['file']}@{w['published']}"
        if key in done:
            continue
        send(token, chat_id, f"📰 <b>{w['title']}</b>\n{w['summary']}\n\n<a href=\"{SITE}report.html?t=weekly&f={w['file']}\">위클리 열기</a>")
        done.add(key)
        print("notified:", key)
    state["notified_weekly"] = sorted(done)
    save_json(STATE, state)
    return 0


def notify_daily(token: str) -> int:
    state = load_json(STATE, {})
    chat_id = state.get("chat_id")
    if not chat_id:
        return 0
    done = set(state.get("notified_daily", []))
    idx = load_json(DATA / "daily" / "index.json", [])
    kind = {"us": "🇺🇸 미국장", "kr": "🇰🇷 한국장"}
    for w in sorted(idx, key=lambda x: (x["date"], x["published"])):
        key = w["file"]
        if key in done:
            continue
        send(token, chat_id, f"{kind.get(w['kind'], '')} <b>{w['title']}</b>\n{w['summary']}\n\n<a href=\"{SITE}report.html?t=daily&f={w['file']}\">데일리 열기</a>")
        done.add(key)
        print("notified:", key)
    state["notified_daily"] = sorted(done)[-60:]
    save_json(STATE, state)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--text")
    ap.add_argument("--reports", action="store_true")
    ap.add_argument("--weekly", action="store_true")
    ap.add_argument("--daily", action="store_true")
    args = ap.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN not set — skip", file=sys.stderr)
        return 0
    if args.setup:
        return setup(token)
    if args.text:
        chat_id = load_json(STATE, {}).get("chat_id")
        send(token, chat_id, args.text)
        return 0
    rc = 0
    if args.reports:
        rc |= notify_reports(token)
    if args.weekly:
        rc |= notify_weekly(token)
    if args.daily:
        rc |= notify_daily(token)
    return rc


if __name__ == "__main__":
    sys.exit(main())
