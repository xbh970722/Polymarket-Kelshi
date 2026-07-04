"""Market calibration logger — zero-cost test of the favorite-longshot bias.

Every loop mark we snapshot quotes of soon-to-settle crypto markets; after they
settle we attach outcomes. A few hundred samples answer empirically whether
Kalshi's short-horizon favorites are underpriced (user's 'inverse strategy'
hypothesis, H5). No trading involved.
"""
import datetime as dt
import sqlite3
from pathlib import Path

from .kalshi_client import KalshiPublic, normalize_market

DB = Path("data") / "market_calibration.db"
SERIES = ["KXBTCD", "KXETHD", "KXBTC15M", "KXETH15M", "KXSOL15M"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS snaps(
  ticker TEXT NOT NULL,
  series TEXT NOT NULL,
  snap_ts TEXT NOT NULL,
  close_time TEXT,
  tau_min REAL,
  yes_bid REAL,
  yes_ask REAL,
  yes_mid REAL,
  result TEXT,
  PRIMARY KEY (ticker, snap_ts)
)
"""


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    return c


def snapshot() -> tuple[int, int]:
    """Record quotes for markets settling within 30 min; resolve past ones."""
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    added = 0
    with _conn() as c:
        for series in SERIES:
            try:
                page = api._get("/markets", series_ticker=series, status="open", limit=100)
            except Exception:
                continue
            for mr in page.get("markets", []):
                m = normalize_market(mr)
                if m["status"] != "active" or not m["close_time"]:
                    continue
                close = dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
                tau = (close - now).total_seconds() / 60.0
                if not (0 < tau <= 30):
                    continue
                if not (m["yes_bid"] > 0 and 0.01 <= m["yes_ask"] <= 0.99):
                    continue
                c.execute("INSERT OR IGNORE INTO snaps VALUES (?,?,?,?,?,?,?,?,NULL)",
                          (m["ticker"], series, now_iso, m["close_time"], round(tau, 1),
                           m["yes_bid"], m["yes_ask"],
                           round((m["yes_bid"] + m["yes_ask"]) / 2, 4)))
                added += c.execute("SELECT changes()").fetchone()[0]
        # resolve outcomes for snapshots whose market has settled
        unresolved = [r["ticker"] for r in c.execute(
            "SELECT DISTINCT ticker FROM snaps WHERE result IS NULL AND close_time < ?",
            (now_iso,))]
        resolved = 0
        for t in unresolved[:40]:                      # rate-limit friendliness
            try:
                mk = api.market(t)
            except Exception:
                continue
            if mk.get("status") in ("settled", "finalized") and mk.get("result") in ("yes", "no"):
                c.execute("UPDATE snaps SET result=? WHERE ticker=?", (mk["result"], t))
                resolved += 1
    return added, resolved


def report() -> str:
    """Empirical calibration: implied (mid) vs realized win rate by price bucket."""
    with _conn() as c:
        rows = c.execute("SELECT yes_mid, result, tau_min FROM snaps "
                         "WHERE result IN ('yes','no') AND tau_min <= 20").fetchall()
    if not rows:
        return "no resolved calibration samples yet"
    buckets: dict = {}
    for r in rows:
        b = min(int(r["yes_mid"] * 10), 9)             # 0.0-0.1 ... 0.9-1.0
        n, wins, mids = buckets.get(b, (0, 0, 0.0))
        buckets[b] = (n + 1, wins + (1 if r["result"] == "yes" else 0),
                      mids + r["yes_mid"])
    lines = [f"market calibration ({len(rows)} samples, tau<=20m):",
             "bucket | n | implied | realized | bias"]
    for b in sorted(buckets):
        n, wins, mids = buckets[b]
        imp, real = mids / n, wins / n
        lines.append(f"{b/10:.1f}-{(b+1)/10:.1f} | {n:4d} | {imp:.3f} | {real:.3f} | "
                     f"{real - imp:+.3f}")
    return "\n".join(lines)
