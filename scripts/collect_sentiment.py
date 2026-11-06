"""시장 심리·보조지표 수집 → data/sentiment.json

CNN Fear & Greed (공포탐욕 지수, Put/Call 5일 평균) — 키 불필요
FRED (T10Y2Y 장단기 금리차, DTWEXBGS 광의 달러지수, STLFSI4 금융 스트레스) — fredgraph.csv, 키 불필요
"""
import csv
import io
import sys
from datetime import datetime, timedelta, timezone
from common import DATA, get_text, keep_previous, load_json, now_iso, save_json

OUT = DATA / "sentiment.json"
CNN_PAGE = "https://www.cnn.com/markets/fear-and-greed"
FRED = [
    ("yield-curve", "T10Y2Y", "미국 장단기 금리차", "10년 − 2년 · %p", 2),
    ("broad-dollar", "DTWEXBGS", "광의 달러지수", "무역가중 · 2006.01=100", 2),
    ("financial-stress", "STLFSI4", "금융 스트레스 지수", "세인트루이스 연준 · 0=장기평균", 3),
]


def comparisons(points: list[dict]) -> dict:
    last = datetime.strptime(points[-1]["date"], "%Y-%m-%d")
    out = {}
    for label, days in (("1w", 7), ("1m", 30), ("1y", 365)):
        cut = (last - timedelta(days=days)).strftime("%Y-%m-%d")
        old = [p for p in points if p["date"] <= cut]
        out[label] = old[-1]["value"] if old else None
    return out


def series_item(id_, name, subtitle, points, digits, **extra) -> dict:
    points = sorted(points, key=lambda p: p["date"])
    if not points:
        raise ValueError("empty")
    cutoff = (datetime.strptime(points[-1]["date"], "%Y-%m-%d") - timedelta(days=366)).strftime("%Y-%m-%d")
    return {"id": id_, "name": name, "subtitle": subtitle, "digits": digits, "status": "ok",
            "value": points[-1]["value"], "asOf": points[-1]["date"],
            "change": (points[-1]["value"] - points[-2]["value"]) if len(points) > 1 else None,
            "comparisons": comparisons(points), "points": [p for p in points if p["date"] >= cutoff],
            "collectedAt": now_iso(), **extra}


def cnn() -> list[dict]:
    start = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%d")
    payload = _cnn_get(start)

    def pts(section, lo, hi):
        uniq = {}
        for p in (section or {}).get("data", []):
            x, y = p.get("x"), p.get("y")
            if not isinstance(y, (int, float)) or not (lo <= y <= hi):
                continue
            ts = x / 1000 if isinstance(x, (int, float)) else None
            if ts is None:
                continue
            uniq[datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")] = {"date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"), "value": y}
        return list(uniq.values())

    fg = payload.get("fear_and_greed", {})
    fg_pts = pts(payload.get("fear_and_greed_historical"), 0, 100)
    score = fg.get("score")
    if isinstance(score, (int, float)):
        d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        fg_pts = [p for p in fg_pts if p["date"] != d] + [{"date": d, "value": score}]
    item_fg = series_item("fear-greed", "공포·탐욕 지수", "CNN Business · 미국 주식 · 0=극단적 공포, 100=극단적 탐욕",
                          fg_pts, 0, rating=fg.get("rating"), source=CNN_PAGE)
    item_pc = series_item("put-call", "Put/Call Ratio", "CNN · 풋/콜 거래량 5일 평균 · 높을수록 풋 우위",
                          pts(payload.get("put_call_options"), 0, 10), 2,
                          rating=(payload.get("put_call_options") or {}).get("rating"), source=CNN_PAGE)
    return [item_fg, item_pc]


def _cnn_get(start: str):
    import requests
    from common import HEADERS
    r = requests.get(f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start}",
                     headers={**HEADERS, "Referer": CNN_PAGE}, timeout=25)
    r.raise_for_status()
    return r.json()


def fred(id_, series, name, subtitle, digits) -> dict:
    text = get_text(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", timeout=25)
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    head = rows[0]
    if len(head) != 2 or head[1] != series:
        raise ValueError("wrong FRED series")
    points = []
    for date, raw in rows[1:]:
        if raw.strip() in ("", "."):
            continue
        try:
            points.append({"date": date, "value": round(float(raw), digits)})
        except ValueError:
            continue
    return series_item(id_, name, subtitle, points[-800:], digits, source=f"https://fred.stlouisfed.org/series/{series}")


def main() -> int:
    prev = {i["id"]: i for i in load_json(OUT, {}).get("items", [])}
    items = []
    try:
        items += cnn()
    except Exception as e:
        print(f"cnn: FAIL {type(e).__name__}: {e}", file=sys.stderr)
        items += [{"id": "fear-greed", "status": "unavailable"}, {"id": "put-call", "status": "unavailable"}]
    for id_, series, name, subtitle, digits in FRED:
        try:
            items.append(fred(id_, series, name, subtitle, digits))
        except Exception as e:
            print(f"{id_}: FAIL {type(e).__name__}: {e}", file=sys.stderr)
            items.append({"id": id_, "status": "unavailable"})
    items = [keep_previous(i, prev.get(i["id"])) for i in items]
    for i in items:
        print(f"{i['id']}: {i['status']} value={i.get('value')} asOf={i.get('asOf')}")
    save_json(OUT, {"schemaVersion": 1, "collectedAt": now_iso(), "items": items})
    return 0


if __name__ == "__main__":
    sys.exit(main())
