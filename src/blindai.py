"""Blind-AI crypto experiment (user idea, 2026-07-04): do LLM blind directional
calls beat the market on short-horizon crypto?

Discipline: the AI is shown ONLY recent price action + the question — never the
Kalshi market price (anti-anchoring). The record step fetches the market price
INDEPENDENTLY, purely for scoring, so the estimate stays blind. Zero money:
this logs calls and, after settlement, compares blind-AI Brier vs market Brier.
If AI beats the market over enough samples, a real lane can be justified; if not,
the idea is rejected with data — same playbook as H5.
"""
import datetime as dt
import sqlite3
from pathlib import Path

import requests

from .kalshi_client import KalshiPublic, normalize_market

DB = Path("data") / "blind_ai.db"
SERIES = ["KXBTCD", "KXETHD"]
PRODUCT = {"KXBTCD": "BTC-USD", "KXETHD": "ETH-USD"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls(
  ticker TEXT PRIMARY KEY,
  question TEXT,
  context TEXT,
  close_time TEXT,
  call_ts TEXT,
  ai_yes REAL,
  ai_claude REAL,
  ai_codex REAL,
  market_yes REAL,
  result TEXT,
  settled_ts TEXT
)
"""


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    return c


def _strike(ticker: str):
    tail = ticker.rsplit("-", 1)[-1]
    if tail.startswith("T"):
        try:
            return float(tail[1:])
        except ValueError:
            return None
    return None


def _price_action(product: str) -> str:
    """Recent price action WITHOUT any market/prediction price — the only input the AI gets."""
    s = requests.Session()
    s.headers["User-Agent"] = "blindai/0.1"
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(minutes=65)
    r = s.get(f"https://api.exchange.coinbase.com/products/{product}/candles",
              params={"granularity": 60, "start": start.isoformat(), "end": end.isoformat()},
              timeout=20)
    r.raise_for_status()
    candles = sorted(r.json())
    closes = [c[4] for c in candles]
    spot = float(s.get(f"https://api.exchange.coinbase.com/products/{product}/ticker",
                       timeout=15).json()["price"])
    if len(closes) < 20:
        return f"spot={spot:.2f}; insufficient history"
    hi, lo = max(c[2] for c in candles), min(c[1] for c in candles)
    r15 = (spot / closes[-15] - 1) * 100 if len(closes) >= 15 else 0
    r60 = (spot / closes[0] - 1) * 100
    return (f"spot={spot:.2f}; last60m: high={hi:.2f} low={lo:.2f} "
            f"return_15m={r15:+.2f}% return_60m={r60:+.2f}%")


def pick_context(cfg=None) -> dict | None:
    """Choose one crypto market settling in 20-50 min, not already logged, and build
    a BLIND context packet (question + price action, NO market price)."""
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc)
    with _conn() as c:
        logged = {r["ticker"] for r in c.execute("SELECT ticker FROM calls")}
    for series in SERIES:
        try:
            page = api._get("/markets", series_ticker=series, status="open", limit=100)
        except Exception:
            continue
        best = None          # pick the strike nearest the money (uncertain = interesting)
        best_dist = 9.0
        for mr in page.get("markets", []):
            m = normalize_market(mr)
            k = _strike(m["ticker"])
            if k is None or m["status"] != "active" or not m["close_time"]:
                continue
            if m["ticker"] in logged or not (m["yes_bid"] > 0 and 0.15 <= m["yes_ask"] <= 0.85):
                continue
            tau = (dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
                   - now).total_seconds() / 60
            # [15,55] window (was [20,50]): with hourly closes, a :40-ish scan sat in a
            # permanent dead zone (16min too close / 76min too far) - review 2026-07-04
            if not (15 <= tau <= 55):
                continue
            dist = abs((m["yes_bid"] + m["yes_ask"]) / 2 - 0.5)   # closeness to 50/50
            if dist < best_dist:
                best_dist = dist
                best = (m["ticker"], m.get("title") or "", k, m["close_time"])
        if best:
            ctx = _price_action(PRODUCT[series])
            return {"ticker": best[0], "question": best[1], "strike": best[2],
                    "close_time": best[3], "context": ctx, "series": series}
    return None


def record(ticker: str, ai_yes: float, ai_claude: float = None, ai_codex: float = None) -> None:
    """Log the blind call and fetch the market price INDEPENDENTLY (for scoring only)."""
    api = KalshiPublic()
    m = api.market_norm(ticker)
    market_yes = round((m["yes_bid"] + m["yes_ask"]) / 2, 4) if m["yes_bid"] else round(m["yes_ask"], 4)
    with _conn() as c:
        row = c.execute("SELECT question, close_time, context FROM calls WHERE ticker=?",
                        (ticker,)).fetchone()
        q = row["question"] if row else (m.get("title") or "")
        ct = row["close_time"] if row else m.get("close_time")
        ctx = row["context"] if row else ""
        c.execute("INSERT OR REPLACE INTO calls(ticker,question,context,close_time,call_ts,"
                  "ai_yes,ai_claude,ai_codex,market_yes,result,settled_ts) "
                  "VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL)",
                  (ticker, q, ctx, ct, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   round(ai_yes, 4), ai_claude, ai_codex, market_yes))


def stash_context(ctx: dict) -> None:
    """Pre-store the question/context so record() keeps them (optional)."""
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO calls(ticker,question,context,close_time,call_ts,"
                  "ai_yes,market_yes) VALUES(?,?,?,?,NULL,NULL,NULL)",
                  (ctx["ticker"], ctx["question"], ctx["context"], ctx["close_time"]))


def settle() -> int:
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    done = 0
    with _conn() as c:
        pend = [r["ticker"] for r in c.execute(
            "SELECT ticker FROM calls WHERE result IS NULL AND ai_yes IS NOT NULL "
            "AND close_time < ?", (now,))]
        for t in pend[:40]:
            try:
                mk = api.market(t)
            except Exception:
                continue
            if mk.get("status") in ("settled", "finalized") and mk.get("result") in ("yes", "no"):
                c.execute("UPDATE calls SET result=?, settled_ts=? WHERE ticker=?",
                          (mk["result"], now, t))
                done += 1
    return done


def report() -> str:
    with _conn() as c:
        rows = c.execute("SELECT ai_yes, market_yes, result FROM calls "
                         "WHERE result IN ('yes','no') AND ai_yes IS NOT NULL "
                         "AND market_yes IS NOT NULL").fetchall()
    n = len(rows)
    if n == 0:
        return "blind-AI: no scored calls yet"
    b_ai = b_mkt = ai_dir = mkt_dir = 0.0
    for r in rows:
        o = 1.0 if r["result"] == "yes" else 0.0
        b_ai += (r["ai_yes"] - o) ** 2
        b_mkt += (r["market_yes"] - o) ** 2
        ai_dir += ((r["ai_yes"] >= 0.5) == (o == 1.0))
        mkt_dir += ((r["market_yes"] >= 0.5) == (o == 1.0))
    verdict = ("AI 胜" if b_ai < b_mkt else "市场 胜")
    return (f"blind-AI: {n} scored | Brier(AI) {b_ai/n:.4f} vs Brier(market) {b_mkt/n:.4f} "
            f"-> {verdict} | 方向命中 AI {ai_dir/n:.0%} vs 市场 {mkt_dir/n:.0%} "
            f"| 判据: n>=50 且 Brier(AI)<Brier(market) 才考虑开真钱")
