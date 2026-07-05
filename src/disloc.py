"""H12 dislocation-harvest SHADOW detector (user insight 2026-07-05: the pit a
stop-hunter smashes is the harvester's meal).

Backfill study (919 drop events, 400 classified): 52% of sharp favorite-price
drops are BOOK-ONLY (spot flat) and buying the dip printed +17.1c/contract with
87.5% win — 3-10x the normal harvest edge, at prices BELOW the favorites zone
floor. But those are PRINT prices (ceiling). This detector measures the FORWARD
fillable version: every mark it compares each market's favorite mid against the
previous scan; a drop >=8c with quiet spot logs the actual STANDING ASK at
detection — the price a live dislocation gate would really pay.

Pre-registered gate (SHORTCYCLE_DESIGN.md H12): n>=40 BOOK-ONLY events with
ask-based EV >= +8c/contract -> propose a live dislocation entry to the panel
and user; ask-based EV <= 0 at n>=40 -> archive H12.
"""
import datetime as dt
import sqlite3
from pathlib import Path

import requests

from .kalshi_client import KalshiPublic, normalize_market, taker_fee_usd
from .shortcycle import strike_of

DB = Path("data") / "disloc_shadow.db"
PROD = {"KXBTC": "BTC-USD", "KXETH": "ETH-USD", "KXSOL": "SOL-USD",
        "KXXRP": "XRP-USD"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS state(
  ticker TEXT PRIMARY KEY, ts TEXT, fav_mid REAL, side_yes INTEGER, spot REAL);
CREATE TABLE IF NOT EXISTS events(
  ticker TEXT, ts TEXT, series TEXT, side TEXT,
  prev_mid REAL, cur_mid REAL, ask REAL, fee REAL,
  spot_prev REAL, spot_cur REAL, strike REAL, tau_min REAL, class TEXT,
  close_time TEXT, result TEXT, settled_ts TEXT,
  PRIMARY KEY (ticker, ts));
"""


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def scan(cfg: dict) -> int:
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    series_list = list(dict.fromkeys(
        (cfg.get("favorites", {}).get("series") or [])
        + (cfg.get("h10", {}).get("series_shadow") or [])))
    spots: dict = {}
    s = requests.Session()
    s.headers["User-Agent"] = "disloc/0.1"
    events = 0
    with _conn() as c:
        for series in series_list:
            prod = PROD.get(series[:5])
            try:
                markets = api.open_markets(series)
            except Exception:
                continue
            if prod and prod not in spots:
                try:
                    spots[prod] = float(s.get(
                        "https://api.exchange.coinbase.com/products/"
                        f"{prod}/ticker", timeout=10).json()["price"])
                except Exception:
                    spots[prod] = None
            spot_cur = spots.get(prod)
            for mr in markets:
                m = normalize_market(mr)
                if m["status"] != "active" or not m["close_time"]:
                    continue
                if not (m["yes_bid"] > 0 and 0.01 <= m["yes_ask"] <= 0.99):
                    continue
                close = dt.datetime.fromisoformat(
                    m["close_time"].replace("Z", "+00:00"))
                tau = (close - now).total_seconds() / 60.0
                if tau < 5:
                    continue
                mid_yes = (m["yes_bid"] + m["yes_ask"]) / 2
                prev = c.execute("SELECT * FROM state WHERE ticker=?",
                                 (m["ticker"],)).fetchone()
                # detect against the PREVIOUS scan (fresh enough to be a "drop")
                if prev is not None:
                    try:
                        age_min = (now - dt.datetime.fromisoformat(prev["ts"])
                                   ).total_seconds() / 60
                    except Exception:
                        age_min = 999
                    side_yes = bool(prev["side_yes"])
                    cur_mid = mid_yes if side_yes else 1 - mid_yes
                    if (age_min <= 12 and prev["fav_mid"] >= 0.78
                            and cur_mid <= prev["fav_mid"] - 0.08):
                        strike = strike_of(m["ticker"])
                        sp, sc = prev["spot"], spot_cur
                        klass = "UNKNOWN"
                        if sp and sc and strike:
                            move = abs(sc - sp) / sp
                            crossed = (sp - strike) * (sc - strike) < 0
                            toward = abs(sc - strike) < abs(sp - strike)
                            if move < 0.0012 and not crossed:
                                klass = "BOOK-ONLY"
                            elif crossed or (toward and move >= 0.0025):
                                klass = "SPOT-MOVE"
                            else:
                                klass = "AMBIGUOUS"
                        ask = m["yes_ask"] if side_yes else m["no_ask"]
                        c.execute(
                            "INSERT OR IGNORE INTO events VALUES"
                            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
                            (m["ticker"], now_iso, series,
                             "yes" if side_yes else "no",
                             round(prev["fav_mid"], 4), round(cur_mid, 4),
                             round(ask, 4), taker_fee_usd(ask, 1),
                             sp, sc, strike, round(tau, 1), klass,
                             m["close_time"]))
                        events += 1
                        print(f"DISLOC {m['ticker']}: fav {prev['fav_mid']:.2f}"
                              f"->{cur_mid:.2f} ask {ask:.2f} [{klass}] "
                              f"tau {tau:.0f}m")
                # update state: track whichever side is currently the favorite
                side_now = mid_yes >= 0.5
                fav_now = mid_yes if side_now else 1 - mid_yes
                c.execute("INSERT OR REPLACE INTO state VALUES(?,?,?,?,?)",
                          (m["ticker"], now_iso, round(fav_now, 4),
                           int(side_now), spot_cur))
    return events


def settle() -> int:
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    done = 0
    with _conn() as c:
        pend = [r["ticker"] for r in c.execute(
            "SELECT DISTINCT ticker FROM events WHERE result IS NULL "
            "AND close_time < ?", (now,))]
        for t in pend[:40]:
            try:
                mk = api.market(t)
            except Exception:
                continue
            if mk.get("status") in ("settled", "finalized") and \
                    mk.get("result") in ("yes", "no"):
                c.execute("UPDATE events SET result=?, settled_ts=? "
                          "WHERE ticker=? AND result IS NULL",
                          (mk["result"], now, t))
                done += 1
        # prune stale state rows so the table stays tiny
        cutoff = (dt.datetime.now(dt.timezone.utc)
                  - dt.timedelta(hours=3)).isoformat(timespec="seconds")
        c.execute("DELETE FROM state WHERE ts < ?", (cutoff,))
    return done


def report() -> str:
    with _conn() as c:
        rows = c.execute("SELECT class, side, ask, fee, result FROM events "
                         "WHERE result IN ('yes','no')").fetchall()
        n_open = c.execute("SELECT COUNT(*) FROM events WHERE result IS NULL"
                           ).fetchone()[0]
    if not rows:
        return f"disloc shadow: 0 settled ({n_open} pending)"
    per: dict = {}
    for r in rows:
        won = r["result"] == r["side"]
        net = (1 - r["ask"] - r["fee"]) if won else (-r["ask"] - r["fee"])
        d = per.setdefault(r["class"], [0, 0, 0.0])
        d[0] += 1
        d[1] += 1 if won else 0
        d[2] += net
    parts = []
    for k, (n, w, tot) in sorted(per.items()):
        parts.append(f"{k}: n={n} win {w / n:.0%} EV {tot / n * 100:+.1f}c")
    bo = per.get("BOOK-ONLY")
    gate = "accumulating"
    if bo and bo[0] >= 40:
        gate = ("PROPOSE-LIVE" if bo[2] / bo[0] >= 0.08 else
                "ARCHIVE" if bo[2] / bo[0] <= 0 else "accumulating")
    return f"disloc shadow: {' | '.join(parts)} | gate: {gate} ({n_open} pending)"
