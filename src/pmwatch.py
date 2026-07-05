"""H14 Polymarket cross-exchange watcher (user idea 2026-07-05): read-only
Polymarket public data as a second opinion on the SAME underlying events
Kalshi trades. No Polymarket trading (US restriction) — data only.

Logs, at every mark, aligned pairs (poly_mid, kalshi_mid, spot) for the
crypto up/down families (hourly + 15m + 5m where matchable). After a few
days: lead-lag analysis (who moves first), divergence calibration (when they
disagree by >=X, who is right), and upgrades: lag-gate confirmation input,
H12b dislocation classifier (a Kalshi drop Polymarket ignores = book-only).

Pre-registered gates (SHORTCYCLE_DESIGN H14): n>=300 aligned pairs, then
(a) if |divergence|>=5c events resolve toward Polymarket >=60% -> add
poly-confirmation to the lag gate (panel review); (b) if toward Kalshi or
noise -> archive H14, keep the logger (cheap).
"""
import datetime as dt
import json
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .kalshi_client import KalshiPublic, normalize_market

DB = Path("data") / "pmwatch.db"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
COINS = {"bitcoin": "KXBTC", "ethereum": "KXETH",
         "solana": "KXSOL", "xrp": "KXXRP"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS pairs(
  ts TEXT, coin TEXT, family TEXT, end_utc TEXT,
  poly_mid REAL, kalshi_ticker TEXT, kalshi_mid REAL, kalshi_strike REAL,
  PRIMARY KEY (ts, coin, family)
)
"""


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    return c


def _poly_events(s: requests.Session) -> list[dict]:
    """Imminent Up-or-Down events (next ~75 min) via endDate window filter."""
    now = dt.datetime.now(dt.timezone.utc)
    try:
        r = s.get(f"{GAMMA}/events",
                  params={"closed": "false", "limit": 100,
                          "end_date_min": now.isoformat(),
                          "end_date_max": (now + dt.timedelta(minutes=75)).isoformat()},
                  timeout=20)
        r.raise_for_status()
        evs = r.json() or []
    except Exception:
        evs = []
    out = [e for e in evs if "up or down" in (e.get("title") or "").lower()]
    if out:
        return out
    # fallback: hourly slug for the next ET top-of-hour
    et = dt.datetime.now(ZoneInfo("America/New_York"))
    nxt = (et + dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    h12 = nxt.hour % 12 or 12
    ampm = "am" if nxt.hour < 12 else "pm"
    month = nxt.strftime("%B").lower()
    for coin in COINS:
        try:
            r = s.get(f"{GAMMA}/events",
                      params={"slug": f"{coin}-up-or-down-{month}-{nxt.day}-"
                                      f"{h12}{ampm}-et"}, timeout=15)
            r.raise_for_status()
            out += r.json() or []
        except Exception:
            continue
    return out


def _poly_mid(s: requests.Session, market: dict) -> float | None:
    """CLOB midpoint of the first (Up/Yes) token; gamma outcomePrices fallback."""
    try:
        toks = market.get("clobTokenIds")
        toks = json.loads(toks) if isinstance(toks, str) else toks
        if toks:
            r = s.get(f"{CLOB}/midpoint", params={"token_id": toks[0]}, timeout=15)
            r.raise_for_status()
            mid = float(r.json().get("mid"))
            if 0.001 <= mid <= 0.999:
                return mid
    except Exception:
        pass
    try:
        pr = market.get("outcomePrices")
        pr = json.loads(pr) if isinstance(pr, str) else pr
        mid = float(pr[0])
        if 0.001 <= mid <= 0.999:
            return mid
    except Exception:
        pass
    return None


def scan() -> int:
    s = requests.Session()
    s.headers["User-Agent"] = "pmwatch/0.1 (read-only research)"
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    logged = 0
    events = _poly_events(s)
    # preload Kalshi families once per prefix actually needed
    kalshi_cache: dict = {}
    with _conn() as c:
        for ev in events:
            title = (ev.get("title") or "").lower()
            coin = next((k for k in COINS if k in title), None)
            if coin is None or not ev.get("endDate"):
                continue
            try:
                end = dt.datetime.fromisoformat(
                    str(ev["endDate"]).replace("Z", "+00:00"))
            except Exception:
                continue
            mks = ev.get("markets") or []
            if not mks:
                continue
            pm = _poly_mid(s, mks[0])
            if pm is None:
                continue
            # family from title window markers: hourly has no :MM range;
            # 5m windows show :05/:35-style ends; 15m show :15/:30/:45
            family = "hourly"
            if any(x in title for x in (":05", ":10", ":20", ":25", ":35",
                                        ":40", ":50", ":55")):
                family = "5m"
            elif any(x in title for x in (":15", ":30", ":45")):
                family = "15m"
            # Kalshi counterpart: ONLY the 15m family aligns 1:1 (both reference
            # the previous window settlement). Hourly poly = up/down from window
            # open vs Kalshi strike ladder = different events (first live pairs
            # showed p90 61c "divergence" = matching artifact); 5m has no Kalshi
            # family. Poly-side rows still log for those (reference series).
            prefix = COINS[coin]
            series = prefix + "15M" if family == "15m" else None
            k_mid = k_strike = None
            k_tkr = None
            if series:
                if series not in kalshi_cache:
                    try:
                        kalshi_cache[series] = [
                            normalize_market(m) for m in api.open_markets(series)]
                    except Exception:
                        kalshi_cache[series] = []
                best = None
                for m in kalshi_cache[series]:
                    if m["status"] != "active" or not m["close_time"]:
                        continue
                    try:
                        kc = dt.datetime.fromisoformat(
                            m["close_time"].replace("Z", "+00:00"))
                    except Exception:
                        continue
                    if abs((kc - end).total_seconds()) > 90:
                        continue
                    if not (m["yes_bid"] > 0 and 0.01 <= m["yes_ask"] <= 0.99):
                        continue
                    mid = (m["yes_bid"] + m["yes_ask"]) / 2
                    d = abs(mid - 0.5)
                    if best is None or d < best[0]:
                        best = (d, m["ticker"], mid)
                if best:
                    k_tkr, k_mid = best[1], round(best[2], 4)
                    from .shortcycle import strike_of
                    k_strike = strike_of(best[1])
            c.execute("INSERT OR IGNORE INTO pairs VALUES(?,?,?,?,?,?,?,?)",
                      (now_iso, coin, family,
                       end.isoformat(timespec="seconds"), round(pm, 4),
                       k_tkr, k_mid, k_strike))
            logged += 1
    return logged


def report() -> str:
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM pairs").fetchone()[0]
        n_matched = c.execute("SELECT COUNT(*) FROM pairs "
                              "WHERE kalshi_mid IS NOT NULL").fetchone()[0]
        rows = c.execute("SELECT poly_mid, kalshi_mid FROM pairs "
                         "WHERE kalshi_mid IS NOT NULL").fetchall()
    if not rows:
        return f"pmwatch: {n} rows, 0 matched pairs yet"
    div = [abs(r["poly_mid"] - r["kalshi_mid"]) for r in rows]
    div.sort()
    return (f"pmwatch: {n} rows, {n_matched} kalshi-matched | |divergence| "
            f"median {div[len(div) // 2] * 100:.1f}c, p90 "
            f"{div[int(len(div) * 0.9)] * 100:.1f}c (gate n>=300)")
