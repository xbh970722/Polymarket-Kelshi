"""W2 weather longshot-fade SHADOW lane (9-seat panel arbitration 2026-07-05).

Buy the NO side of .15-.40-quoted YES buckets, tau 8-48h — SHADOW ONLY: the
$0.50 weather cap cannot buy a 0.85-0.90 NO contract (user keeps caps low), so
this logs the exact would-buy at the REAL standing no_ask and measures how much
of the print-implied edge survives live books.

Pre-registered gate (research/WEATHER_LANES.md): 7-10 shadow days AND >=60% of
print edge surviving (net >= +3c/contract) -> ask the user about the cap;
otherwise W2 archives. Longshot-hit monitor: any settled YES in the .03-.15
band is a regime alarm (baseline 0/1487 over 66 days).
"""
import datetime as dt
import sqlite3
from pathlib import Path

from .kalshi_client import KalshiPublic, normalize_market, taker_fee_usd

DB = Path("data") / "wxfade_shadow.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow(
  ticker TEXT PRIMARY KEY,
  ts TEXT, series TEXT,
  yes_bid REAL, yes_ask REAL, no_ask REAL, fee REAL, tau_h REAL,
  close_time TEXT, result TEXT, settled_ts TEXT
)
"""


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    return c


def scan(cfg: dict) -> int:
    """Log would-buy NO entries: YES quoted .15-.40, tau in (8,48] hours,
    two-sided book. One observation per market (first scan in window owns it)."""
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc)
    logged = 0
    series_list = cfg.get("weather", {}).get("series") or []
    with _conn() as c:
        for series in series_list:
            try:
                markets = api.open_markets(series)
            except Exception as e:
                print(f"WARN wxfade {series}: fetch failed ({e})")
                continue
            for mr in markets:
                m = normalize_market(mr)
                if m["status"] != "active" or not m["close_time"]:
                    continue
                close = dt.datetime.fromisoformat(
                    m["close_time"].replace("Z", "+00:00"))
                tau_h = (close - now).total_seconds() / 3600.0
                if not (8 < tau_h <= 48):
                    continue
                if not (m["yes_bid"] > 0 and 0.01 <= m["yes_ask"] <= 0.99):
                    continue
                mid = (m["yes_bid"] + m["yes_ask"]) / 2
                if not (0.15 <= mid <= 0.40):
                    continue
                no_ask = m["no_ask"]
                if not (0.01 <= no_ask <= 0.98):
                    continue
                fee = taker_fee_usd(no_ask, 1)
                c.execute("INSERT OR IGNORE INTO shadow(ticker,ts,series,yes_bid,"
                          "yes_ask,no_ask,fee,tau_h,close_time) "
                          "VALUES(?,?,?,?,?,?,?,?,?)",
                          (m["ticker"], now.isoformat(timespec="seconds"), series,
                           m["yes_bid"], m["yes_ask"], round(no_ask, 4), fee,
                           round(tau_h, 1), m["close_time"]))
                if c.execute("SELECT changes()").fetchone()[0]:
                    logged += 1
    return logged


def settle() -> int:
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    done = 0
    with _conn() as c:
        pend = [r["ticker"] for r in c.execute(
            "SELECT ticker FROM shadow WHERE result IS NULL AND close_time < ?",
            (now,))]
        for t in pend[:40]:
            try:
                mk = api.market(t)
            except Exception:
                continue
            if mk.get("status") in ("settled", "finalized") and \
                    mk.get("result") in ("yes", "no"):
                c.execute("UPDATE shadow SET result=?, settled_ts=? WHERE ticker=?",
                          (mk["result"], now, t))
                done += 1
    return done


def report() -> str:
    with _conn() as c:
        rows = c.execute("SELECT no_ask, fee, result FROM shadow "
                         "WHERE result IN ('yes','no')").fetchall()
        n_open = c.execute("SELECT COUNT(*) FROM shadow WHERE result IS NULL"
                           ).fetchone()[0]
    n = len(rows)
    if n == 0:
        return f"wxfade shadow: 0 settled ({n_open} pending)"
    tot = 0.0
    wins = 0
    for r in rows:
        won = r["result"] == "no"          # we bought NO
        wins += 1 if won else 0
        tot += (1 - r["no_ask"] - r["fee"]) if won else (-r["no_ask"] - r["fee"])
    mean = tot / n
    gate = ("USER-DECISION (edge survives)" if n >= 60 and mean >= 0.03 else
            "ARCHIVE (edge dead)" if n >= 60 and mean <= 0 else "accumulating")
    return (f"wxfade shadow: n={n} win {wins / n:.1%} mean net "
            f"{mean * 100:+.1f}c/contract total ${tot:+.2f} | gate: {gate} "
            f"({n_open} pending)")
