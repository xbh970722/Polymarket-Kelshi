"""Scan open Kalshi events in configured categories and emit a research shortlist."""
import datetime as dt
import json
from collections import Counter
from pathlib import Path

import yaml

from .kalshi_client import KalshiPublic, normalize_market

DATA_DIR = Path("data")


def load_config() -> dict:
    return yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))


def scan(cfg: dict) -> list[dict]:
    api = KalshiPublic()
    sc = cfg["scanner"]
    domains = set(cfg["domains"])
    now = dt.datetime.now(dt.timezone.utc)
    seen: Counter = Counter()
    rows: list[dict] = []
    for ev in api.iter_events(max_pages=sc.get("max_pages", 25)):
        cat = ev.get("category") or "?"
        seen[cat] += 1
        if cat not in domains:
            continue
        for m in ev.get("markets") or []:
            row = _evaluate(ev, m, sc, now)
            if row:
                rows.append(row)
    rows.sort(key=lambda r: r["score"], reverse=True)
    shortlist = _dedupe_by_event(rows, sc["shortlist_size"])
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "candidates.json").write_text(
        json.dumps({"generated": now.isoformat(), "categories_seen": dict(seen),
                    "candidates": shortlist}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    return shortlist


def _dedupe_by_event(rows: list[dict], size: int) -> list[dict]:
    """Keep at most 2 markets per event so one hot event can't fill the shortlist."""
    per_event: Counter = Counter()
    out = []
    for r in rows:
        if per_event[r["event_ticker"]] >= 2:
            continue
        per_event[r["event_ticker"]] += 1
        out.append(r)
        if len(out) >= size:
            break
    return out


def _evaluate(ev: dict, m_raw: dict, sc: dict, now: dt.datetime):
    m = normalize_market(m_raw)
    if m["status"] != "active" or m["is_provisional"]:
        return None
    ya, yb, na = m["yes_ask"], m["yes_bid"], m["no_ask"]
    if not (0.01 <= ya <= 0.99 and 0.01 <= na <= 0.99):
        return None
    lo, hi = sc["min_price_cents"] / 100, sc["max_price_cents"] / 100
    if ya <= lo or ya >= hi:
        return None
    spread_cents = (ya - yb) * 100
    if spread_cents > sc["max_spread_cents"]:
        return None
    if m["volume_24h"] < sc["min_volume_24h"] or m["open_interest"] < sc["min_open_interest"]:
        return None
    if not m["close_time"]:
        return None
    close = dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
    days = (close - now).total_seconds() / 86400
    if not (sc["min_days_to_close"] <= days <= sc["max_days_to_close"]):
        return None
    liquidity = min(m["volume_24h"], 20000) / 20000 + min(m["open_interest"], 50000) / 50000
    score = liquidity - spread_cents * 0.05
    return {
        "ticker": m["ticker"],
        "event_ticker": ev.get("event_ticker"),
        "category": ev.get("category"),
        "title": ev.get("title") or "",
        "subtitle": m_raw.get("yes_sub_title") or m_raw.get("subtitle") or "",
        "yes_bid": yb, "yes_ask": ya, "no_ask": na,
        "mid_prob": round((yb + ya) / 2, 4),
        "spread_cents": round(spread_cents, 1),
        "volume_24h": m["volume_24h"], "open_interest": m["open_interest"],
        "close_time": m["close_time"], "days_to_close": round(days, 2),
        "score": round(score, 4),
    }
