"""H10: 15m favorite-harvest — SHADOW ledger + capped ETH micro-probe.

Panel arbitration 2026-07-05 (7 seats: 5 MODIFIED-GO, 1 NO-GO, 1 NEED-MORE-DATA):
no full lane until the pre-registered gate passes on FORWARD scan-time data.
The shadow logs the exact would-buy (real standing ask) at every valid scan —
it IS the gate's measuring instrument. The probe (user-authorized minimal-size
auto test) answers fill-reality only: ETH, 1 contract, hard sample/loss budget,
isolated h10fav15m title so it can never touch the proven hourly lane's brakes.

Pre-registered decision rule (checked by reflection/review tasks):
  shadow n>=150 and mean net >= +0.05 -> propose fast GO
  shadow n>=300 and mean net >= +0.02 -> propose slow GO
  shadow n>=150 and mean net <= 0     -> kill, archive H10
"""
import datetime as dt
import sqlite3
from pathlib import Path

from .kalshi_client import KalshiPublic, normalize_market, taker_fee_usd

DB = Path("data") / "h10_shadow.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow(
  ticker TEXT PRIMARY KEY,
  ts TEXT, series TEXT, side TEXT,
  ask REAL, fee REAL, tau_min REAL,
  close_time TEXT, result TEXT, settled_ts TEXT
)
"""


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    return c


def scan(cfg: dict) -> list[dict]:
    """Scan-time candidates: favorite ask in zone, tau in window, two-sided book.
    Returns them AND logs every one to the shadow ledger (one row per market —
    the first scan that sees it in-window owns the observation)."""
    h = cfg["h10"]
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc)
    zlo, zhi = h["zone"]
    tlo, thi = h["tau_window_min"]
    out = []
    with _conn() as c:
        for series in h["series_shadow"]:
            try:
                markets = api.open_markets(series)
            except Exception as e:
                print(f"WARN {series}: fetch failed ({e})")
                continue
            for mr in markets:
                m = normalize_market(mr)
                if m["status"] != "active" or not m["close_time"]:
                    continue
                close = dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
                tau = (close - now).total_seconds() / 60.0
                if not (tlo < tau <= thi):
                    continue
                if not (m["yes_bid"] > 0 and 0.01 <= m["yes_ask"] <= 0.99):
                    continue
                mid = (m["yes_bid"] + m["yes_ask"]) / 2
                side = "yes" if mid >= 0.5 else "no"
                ask = m["yes_ask"] if side == "yes" else m["no_ask"]
                if not (zlo <= ask <= zhi):
                    continue
                fee = taker_fee_usd(ask, 1)
                c.execute("INSERT OR IGNORE INTO shadow(ticker,ts,series,side,ask,"
                          "fee,tau_min,close_time) VALUES(?,?,?,?,?,?,?,?)",
                          (m["ticker"], now.isoformat(timespec="seconds"), series,
                           side, round(ask, 4), fee, round(tau, 1), m["close_time"]))
                out.append({"ticker": m["ticker"], "series": series, "side": side,
                            "ask": ask, "tau": tau,
                            "mid": round(mid if side == "yes" else 1 - mid, 4)})
        # ---- H13 final-6 shadow (user insight: BTC's volume lives in the last
        # 6 minutes). Different strategy, own pre-registered gate: closing-lock
        # extreme-band harvest at tau<=6, judged on its own rows/thresholds. ----
        f6 = cfg["h10"].get("final6") or {}
        for series in f6.get("series") or []:
            try:
                markets = api.open_markets(series)
            except Exception as e:
                print(f"WARN {series}: fetch failed ({e})")
                continue
            zlo6, zhi6 = f6.get("zone", [0.94, 0.985])
            tlo6, thi6 = f6.get("tau_window_min", [0.5, 6])
            for mr in markets:
                m = normalize_market(mr)
                if m["status"] != "active" or not m["close_time"]:
                    continue
                close = dt.datetime.fromisoformat(
                    m["close_time"].replace("Z", "+00:00"))
                tau = (close - now).total_seconds() / 60.0
                if not (tlo6 < tau <= thi6):
                    continue
                if not (m["yes_bid"] > 0 and 0.01 <= m["yes_ask"] <= 0.99):
                    continue
                mid = (m["yes_bid"] + m["yes_ask"]) / 2
                side = "yes" if mid >= 0.5 else "no"
                ask = m["yes_ask"] if side == "yes" else m["no_ask"]
                if not (zlo6 <= ask <= zhi6):
                    continue
                c.execute("INSERT OR IGNORE INTO shadow(ticker,ts,series,side,ask,"
                          "fee,tau_min,close_time) VALUES(?,?,?,?,?,?,?,?)",
                          (m["ticker"], now.isoformat(timespec="seconds"), series,
                           side, round(ask, 4), taker_fee_usd(ask, 1),
                           round(tau, 1), m["close_time"]))
    return out


def settle() -> int:
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    done = 0
    with _conn() as c:
        pend = [r["ticker"] for r in c.execute(
            "SELECT ticker FROM shadow WHERE result IS NULL AND close_time < ?",
            (now,))]
        for t in pend[:60]:
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
    # R7-C2 LOW: the MAIN gate is judged on tau>6 rows only — H13 final6 rows
    # (tau<=6, its own pre-registered gate) must not blend into this population
    with _conn() as c:
        rows = c.execute("SELECT series, side, ask, fee, result, tau_min "
                         "FROM shadow WHERE result IN ('yes','no')").fetchall()
        n_open = c.execute("SELECT COUNT(*) FROM shadow WHERE result IS NULL"
                           ).fetchone()[0]
    main = [r for r in rows if float(r["tau_min"] or 0) > 6]
    f6 = [r for r in rows if float(r["tau_min"] or 0) <= 6]

    def _net(r):
        won = r["result"] == r["side"]
        return (1 - r["ask"] - r["fee"]) if won else (-r["ask"] - r["fee"])

    if not main and not f6:
        return f"h10 shadow: 0 settled ({n_open} pending)"
    per: dict = {}
    tot = 0.0
    for r in main:
        net = _net(r)
        tot += net
        s = per.setdefault(r["series"], [0, 0.0])
        s[0] += 1
        s[1] += net
    parts = " | ".join(f"{k}: n={v[0]} net ${v[1]:+.2f}" for k, v in per.items())
    n = len(main)
    mean = (tot / n) if n else 0.0
    gate = ("FAST-GO" if n >= 150 and mean >= 0.05 else
            "SLOW-GO" if n >= 300 and mean >= 0.02 else
            "KILL" if n >= 150 and mean <= 0 else "accumulating")
    out = (f"h10 shadow(main): n={n} mean {mean * 100:+.1f}c total ${tot:+.2f}"
           f" | {parts} | gate: {gate} ({n_open} pending)")
    if f6:
        t6 = sum(_net(r) for r in f6)
        w6 = sum(1 for r in f6 if r["result"] == r["side"])
        g6 = ("PROPOSE" if len(f6) >= 150 and t6 / len(f6) >= 0.01
              and (len(f6) - w6) <= 1 else
              "ARCHIVE" if (len(f6) - w6) >= 2 or
              (len(f6) >= 150 and t6 <= 0) else "accumulating")
        out += (f" || H13 final6: n={len(f6)} win {w6}/{len(f6)} "
                f"net ${t6:+.2f} gate: {g6}")
    return out
