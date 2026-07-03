"""SQLite paper/live trade ledger with calibration metrics (Brier score)."""
import datetime as dt
import sqlite3
from pathlib import Path

DB = Path("data") / "ledger.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  mode TEXT NOT NULL,
  ticker TEXT NOT NULL,
  title TEXT,
  side TEXT NOT NULL,
  price REAL NOT NULL,
  contracts INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  fee_usd REAL NOT NULL,
  q_claude REAL,
  q_codex REAL,
  q_consensus REAL,
  market_prob REAL,
  edge_net REAL,
  rationale TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  result TEXT,
  pnl_usd REAL,
  settled_ts TEXT,
  order_id TEXT,
  exit_type TEXT,
  target_price REAL,
  stop_price REAL,
  review_after_ts TEXT,
  exit_price REAL
)
"""

# columns added after the original schema shipped -> additive migration
_MIGRATIONS = {
    "order_id": "TEXT", "exit_type": "TEXT", "target_price": "REAL",
    "stop_price": "REAL", "review_after_ts": "TEXT", "exit_price": "REAL",
}


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(trades)")}
    for name, typ in _MIGRATIONS.items():
        if name not in cols:
            c.execute(f"ALTER TABLE trades ADD COLUMN {name} {typ}")
    return c


def insert_trade(**f) -> int:
    f.setdefault("ts", dt.datetime.now().isoformat(timespec="seconds"))
    cols = ",".join(f)
    with _conn() as c:
        cur = c.execute(f"INSERT INTO trades({cols}) VALUES({','.join('?' * len(f))})",
                        list(f.values()))
        return cur.lastrowid


def open_trades() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM trades WHERE status='open' ORDER BY ts")]


def pending_trades() -> list[dict]:
    """Live orders decided by the engine but not yet confirmed/placed."""
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM trades WHERE status='pending' ORDER BY ts")]


def mark_placed(trade_id: int, order_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE trades SET status='open', order_id=? WHERE id=?",
                  (order_id, trade_id))


def void_trade(trade_id: int, reason: str) -> None:
    with _conn() as c:
        c.execute("UPDATE trades SET status='voided', rationale=rationale || ' | VOID: ' || ? "
                  "WHERE id=?", (reason, trade_id))


def has_open_position(ticker: str) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM trades WHERE status='open' AND ticker=?",
                         (ticker,)).fetchone() is not None


def settle_trade(trade_id: int, result: str, pnl_usd: float) -> None:
    with _conn() as c:
        c.execute("UPDATE trades SET status='settled', result=?, pnl_usd=?, settled_ts=? "
                  "WHERE id=?",
                  (result, pnl_usd, dt.datetime.now().isoformat(timespec="seconds"), trade_id))


def close_position(trade_id: int, exit_price: float, pnl_usd: float, reason: str) -> None:
    """Early exit (swing) before settlement. status='closed' so it is excluded from
    Brier calibration (no resolved outcome) but its P&L still counts in the account."""
    now = dt.datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        c.execute("UPDATE trades SET status='closed', exit_price=?, pnl_usd=?, settled_ts=?, "
                  "result=?, rationale = rationale || ' | EXIT: ' || ? WHERE id=?",
                  (exit_price, pnl_usd, now, reason, reason, trade_id))


def set_exit_plan(trade_id: int, exit_type: str, target_price: float,
                  stop_price: float, review_after_ts: str) -> None:
    with _conn() as c:
        c.execute("UPDATE trades SET exit_type=?, target_price=?, stop_price=?, "
                  "review_after_ts=? WHERE id=?",
                  (exit_type, target_price, stop_price, review_after_ts, trade_id))


def positions_due_for_review(now_iso: str) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM trades WHERE status='open' AND review_after_ts IS NOT NULL "
            "AND review_after_ts <= ? ORDER BY review_after_ts", (now_iso,))]


def stats() -> dict:
    today = dt.date.today().isoformat()
    with _conn() as c:
        risk_today = c.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM trades "
            "WHERE ts LIKE ? || '%' AND status != 'voided'",
            (today,)).fetchone()[0]
        open_exp = c.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM trades "
            "WHERE status IN ('open','pending')").fetchone()[0]
        n_open = c.execute(
            "SELECT COUNT(*) FROM trades WHERE status IN ('open','pending')").fetchone()[0]
        pnl_today = c.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) FROM trades WHERE settled_ts LIKE ? || '%'",
            (today,)).fetchone()[0]
    return {"risk_used_today": risk_today, "open_exposure": open_exp,
            "open_positions": n_open, "realized_pnl_today": pnl_today}


def swing_summary() -> dict:
    with _conn() as c:
        r = c.execute("SELECT COUNT(*) n, COALESCE(SUM(pnl_usd),0) pnl "
                      "FROM trades WHERE status='closed'").fetchone()
    return {"n_closed": r["n"], "swing_pnl": round(r["pnl"], 2)}


def calibration() -> dict:
    """Brier scores answer: was the model actually better calibrated than the market?"""
    with _conn() as c:
        rows = c.execute(
            "SELECT q_consensus, market_prob, side, result, pnl_usd FROM trades "
            "WHERE status='settled' AND result IN ('yes','no')").fetchall()
    n = len(rows)
    if n == 0:
        return {"n_settled": 0}
    b_model = b_market = wins = pnl = 0.0
    for r in rows:
        outcome = 1.0 if r["result"] == "yes" else 0.0
        b_model += (r["q_consensus"] - outcome) ** 2
        b_market += (r["market_prob"] - outcome) ** 2
        wins += (r["side"] == r["result"])
        pnl += r["pnl_usd"] or 0.0
    return {"n_settled": n,
            "brier_model": round(b_model / n, 4),
            "brier_market": round(b_market / n, 4),
            "win_rate": round(wins / n, 4),
            "realized_pnl": round(pnl, 2)}
