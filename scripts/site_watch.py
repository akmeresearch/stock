"""웹페이지 게시판 감시: 새 글이 올라오면 텔레그램으로 알린다 (펩트론 공지 등).

 설정: data/site_watch.json  [{id, name, url, link_re(글 링크 정규식, 그룹1=글 id), base}]
 상태: data/site_watch_state.json  {id: {"seen": [...], "init": true}}
 첫 실행은 기존 글을 모두 '본 것'으로 등록만 하고 알리지 않는다.

실행: python scripts/site_watch.py
환경변수: TELEGRAM_BOT_TOKEN
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONF = DATA / "site_watch.json"
STATE = DATA / "site_watch_state.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "ko-KR,ko;q=0.9"}
KST = timezone(timedelta(hours=9))


def load(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


def text_of(html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    t = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;", " ", t).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def fetch(url: str) -> str:
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    enc = r.apparent_encoding if (r.encoding or "").lower() in ("iso-8859-1", "ascii", "") else r.encoding
    return r.content.decode(enc or "utf-8", errors="replace")


def posts(site: dict, html: str) -> list[dict]:
    out, seen = [], set()
    for m in re.finditer(r"<a[^>]+href=\"([^\"]*" + site["link_re"] + r"[^\"]*)\"[^>]*>(.*?)</a>", html, re.S | re.I):
        href, inner = m.group(1), m.group(2 + site.get("groups", 1))
        pid = m.group(2)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
        if not title or pid in seen:
            continue
        seen.add(pid)
        link = href if href.startswith("http") else site.get("base", "") + href.replace("&amp;", "&")
        # 같은 행의 날짜
        row = html[m.end(): m.end() + 1500]
        dm = re.search(r"(20\d\d[-./]\d\d[-./]\d\d)", row)
        out.append({"id": pid, "title": title, "link": link.replace("&amp;", "&"), "date": dm.group(1) if dm else ""})
    return out


def excerpt(site: dict, link: str, title: str) -> str:
    try:
        t = text_of(fetch(link))
    except Exception as e:
        print(f"  detail: {e}", file=sys.stderr); return ""
    i = t.find(title[:20])
    body = t[i + len(title):] if i >= 0 else t
    body = re.sub(r"^(최고관리자|관리자|작성자|작성일자?|조회|첨부|목록|이전글|다음글|[\d\-.: ]+)\s*", "", body.strip())
    for cut in ("이전글", "다음글", "목록보기", "Copyright", "COPYRIGHT"):
        j = body.find(cut)
        if j > 200:
            body = body[:j]
    return re.sub(r"\s+", " ", body).strip()[:600]


def tg(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = load(DATA / "notify.json", {}).get("chat_id")
    if not token or not chat_id:
        print("  telegram not configured", file=sys.stderr); return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}, timeout=30)
    if not r.ok:
        print(f"  telegram {r.status_code}: {r.text[:200]}", file=sys.stderr)
    return r.ok


def esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> int:
    conf = load(CONF, {"sites": []})
    state = load(STATE, {})
    changed = False
    for site in conf["sites"]:
        st = state.setdefault(site["id"], {"seen": [], "init": False})
        try:
            html = fetch(site["url"])
        except Exception as e:
            print(f"{site['name']}: fetch FAIL {e}", file=sys.stderr); continue
        ps = posts(site, html)
        if not ps:
            print(f"{site['name']}: 글 목록을 찾지 못함 (페이지 구조 변경?)", file=sys.stderr); continue
        seen = set(st["seen"])
        new = [p for p in ps if p["id"] not in seen]
        print(f"{site['name']}: {len(ps)} posts, {len(new)} new")
        if not st["init"]:
            st["seen"] = sorted({p["id"] for p in ps}, key=lambda x: int(x) if x.isdigit() else x)
            st["init"] = True; st["initAt"] = datetime.now(KST).isoformat(timespec="minutes"); changed = True
            print("  initialized (no alerts for existing posts)"); continue
        for p in sorted(new, key=lambda x: int(x["id"]) if x["id"].isdigit() else x["id"]):
            ex = excerpt(site, p["link"], p["title"])
            msg = f"📢 <b>{esc(site['name'])} 새 글</b>\n<b>{esc(p['title'])}</b>{(' · ' + esc(p['date'])) if p['date'] else ''}\n\n{esc(ex)}{'…' if len(ex) >= 600 else ''}\n\n<a href=\"{esc(p['link'])}\">원문 보기</a>"
            ok = tg(msg)
            print(f"  ALERT {p['id']} {p['title'][:50]} sent={ok}")
            st.setdefault("alerts", []).append({"id": p["id"], "title": p["title"], "date": p["date"], "link": p["link"], "at": datetime.now(KST).isoformat(timespec="minutes"), "sent": ok})
            st["alerts"] = st["alerts"][-100:]
            if ok:
                st["seen"].append(p["id"]); changed = True
        st["seen"] = st["seen"][-500:]
        st["checkedAt"] = datetime.now(KST).isoformat(timespec="minutes")
    if changed:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("state saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
