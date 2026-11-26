"""종목 뉴스 감시: 지정 키워드의 새 기사를 모아 텔레그램으로 링크와 함께 보낸다 (펩트론 등).

 소스: 구글뉴스 RSS (한글·영문, 막히면 빙 뉴스). 같은 기사를 여러 매체가 쓰면 하나로 묶어 '외 n개 매체'.
 설정: data/news_watch.json   상태: data/news_state.json
 실행: python scripts/news_watch.py [--hours 6] [--dry-run]   (첫 실행은 등록만)
"""
import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, KST, load_json, now_iso, save_json  # noqa: E402
from deal_watch import google_news, norm_key, tg, esc  # noqa: E402

CONF = DATA / "news_watch.json"
STATE = DATA / "news_state.json"


def tokens(t: str) -> set:
    return {w for w in re.split(r"[^\w]+", t.lower()) if len(w) >= 2}


def cluster(items: list[dict]) -> list[list[dict]]:
    """제목 유사도(자카드 ≥ 0.45)로 같은 기사 묶기."""
    groups = []
    for it in sorted(items, key=lambda x: x["ts"]):
        tk = tokens(it["title"])
        for g in groups:
            gt = tokens(g[0]["title"])
            if tk and gt and len(tk & gt) / len(tk | gt) >= 0.45:
                g.append(it); break
        else:
            groups.append([it])
    return groups


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    conf = load_json(CONF, {"watch": []})
    state = load_json(STATE, {})
    since = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).isoformat()
    keep = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    for w in conf["watch"]:
        st = state.setdefault(w["id"], {"seen": {}, "init": False})
        st["seen"] = {k: v for k, v in st["seen"].items() if v >= keep}
        heads = []
        for q in w.get("queries_ko", []):
            heads += google_news(q, "ko")
        for q in w.get("queries_en", []):
            heads += google_news(q, "en")
        excl = [re.compile(x, re.I) for x in w.get("exclude", [])]
        must = re.compile(w["must"], re.I) if w.get("must") else None
        fresh, keys = [], set()
        for h in heads:
            k = norm_key(h["title"])
            if h["ts"] < since or k in st["seen"] or k in keys:
                continue
            if must and not must.search(h["title"]):
                continue
            if any(x.search(h["title"]) for x in excl):
                st["seen"][k] = h["ts"]; continue
            keys.add(k); fresh.append(h)
        print(f"{w['name']}: {len(heads)} headlines, {len(fresh)} new")
        if not st["init"]:
            for h in heads:
                st["seen"][norm_key(h["title"])] = h["ts"]
            st["init"] = True; print("  initialized (no alerts for existing news)"); continue
        if not fresh:
            continue
        groups = cluster(fresh)[: w.get("max_per_run", 10)]
        if args.dry_run:
            for g in groups:
                print("   ", g[0]["ts"][11:16], g[0]["source"], "|", g[0]["title"][:90], f"(+{len(g) - 1})" if len(g) > 1 else "")
            continue
        lines = [f"📰 <b>{esc(w['name'])} 새 뉴스 {len(groups)}건</b>"]
        for g in groups:
            lead = g[0]
            t = datetime.fromisoformat(lead["ts"]).astimezone(KST).strftime("%H:%M")
            more = f" <i>외 {len(g) - 1}개 매체</i>" if len(g) > 1 else ""
            lines.append(f"\n• <a href=\"{esc(lead['link'])}\">{esc(lead['title'][:120])}</a>\n  {esc(lead['source'])} {t}{more}")
        ok = tg("\n".join(lines))
        print(f"  sent {len(groups)} groups ok={ok}")
        for h in fresh:
            st["seen"][norm_key(h["title"])] = h["ts"]
        st["lastAlert"] = now_iso()
    if not args.dry_run:
        save_json(STATE, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
