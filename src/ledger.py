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
    "booked_ts": "TEXT",   # R4: when cash actually moved (fill/freeze time) —
}                          # the cash identity keys on this, not on decide-time ts


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    # concurrency hardening (panel review 2026-07-04, OPUS-B CRITICAL): the loop's
    # subprocesses, supervisor sessions and interactive scripts all hit this file —
    # WAL lets readers and one writer coexist; busy_timeout waits instead of raising
    # 'database is locked' mid-settle.
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=15000")
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


def active_trades(mode: str | None = None) -> list[dict]:
    """Rows that may hold real exposure: open, pending (intent), OR unknown
    (ambiguous fill). R3-FABLE HIGH: window/correlation dedup must see all
    three — dedup that ignores an ambiguous fill can double real exposure."""
    q = "SELECT * FROM trades WHERE status IN ('open','pending','unknown')"
    args: list = []
    if mode:
        q += " AND mode=?"
        args.append(mode)
    with _conn() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY ts", args)]


def record_fill(trade_id: int, contracts: int, price: float, cost_usd: float,
                fee_usd: float, order_id: str) -> None:
    """CODEX-2 HIGH fix: actual fill + status='open' + order_id in ONE transaction,
    so no crash window can leave a filled trade looking pending (and later voided).
    booked_ts = when the cash actually moved (R4 cash-identity keying)."""
    now = dt.datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        c.execute("UPDATE trades SET contracts=?, price=?, cost_usd=?, fee_usd=?, "
                  "order_id=?, status='open', booked_ts=? WHERE id=?",
                  (contracts, price, cost_usd, fee_usd, order_id, now, trade_id))


def mark_unknown(trade_id: int, reason: str) -> None:
    """Exchange state ambiguous (post-submit exception): freeze the row as 'unknown'
    — counted as exposure, excluded from auto-retry, surfaced by reconcile."""
    now = dt.datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        c.execute("UPDATE trades SET status='unknown', booked_ts=?, "
                  "rationale = rationale || ' | UNKNOWN: ' || ? WHERE id=?",
                  (now, reason, trade_id))


def set_client_oid(trade_id: int, client_oid: str | None) -> None:
    """R4-FABLE-A HIGH fix: give a pending row its order identity BEFORE the POST
    (execute-live lane), or clear it back to NULL after a provable clean reject so
    the stale-pending TTL voids instead of freezing."""
    with _conn() as c:
        c.execute("UPDATE trades SET order_id=? WHERE id=?", (client_oid, trade_id))


def split_close(trade_id: int, filled: int, exit_price: float,
                fee_actual: float, reason: str) -> None:
    """Partial exit fill (CODEX-A fix): close only the filled contracts at the real
    price; shrink the original row to the residual so books match the exchange."""
    now = dt.datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        t = c.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        if not t or filled <= 0 or filled > t["contracts"]:
            return
        frac = filled / t["contracts"]
        cost_f = round(t["cost_usd"] * frac, 2)
        pnl = round(filled * exit_price - fee_actual - cost_f, 2)
        if filled == t["contracts"]:
            c.execute("UPDATE trades SET status='closed', exit_price=?, pnl_usd=?, "
                      "settled_ts=?, result=?, rationale=rationale || ' | EXIT: ' || ? "
                      "WHERE id=?", (exit_price, pnl, now, reason, reason, trade_id))
            return
        rem = t["contracts"] - filled
        c.execute("UPDATE trades SET contracts=?, cost_usd=?, fee_usd=? WHERE id=?",
                  (rem, round(t["cost_usd"] - cost_f, 2),
                   round((t["fee_usd"] or 0) * rem / t["contracts"], 2), trade_id))
        c.execute("INSERT INTO trades(ts,mode,ticker,title,side,price,contracts,cost_usd,"
                  "fee_usd,q_claude,q_codex,q_consensus,market_prob,edge_net,rationale,"
                  "status,result,pnl_usd,settled_ts,exit_price,order_id,exit_type,"
                  "target_price,stop_price,review_after_ts) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (t["ts"], t["mode"], t["ticker"], t["title"], t["side"], t["price"],
                   filled, cost_f, round((t["fee_usd"] or 0) * frac, 2),
                   t["q_claude"], t["q_codex"], t["q_consensus"], t["market_prob"],
                   t["edge_net"], (t["rationale"] or "") + f" | partial EXIT: {reason}",
                   "closed", reason, pnl, now, exit_price,
                   t["order_id"], t["exit_type"], t["target_price"], t["stop_price"],
                   t["review_after_ts"]))   # CODEX-2 LOW: keep the audit linkage


def void_stale_pending(max_age_min: int = 60) -> int:
    """Pending live orders that never executed keep consuming exposure/slots
    forever (OPUS-A MED). R3-FABLE MED refinement: a stale pending WITHOUT an
    order_id provably never reached the exchange (no POST was attempted with
    its identity) -> clean void. Only rows that own an order identity become
    'unknown' (possibly filled; resolver/reconcile owns them)."""
    cutoff = (dt.datetime.now() - dt.timedelta(minutes=max_age_min)
              ).isoformat(timespec="seconds")
    with _conn() as c:
        c.execute("UPDATE trades SET status='voided', "
                  "rationale = rationale || ' | VOID: stale pending, never submitted' "
                  "WHERE status='pending' AND ts < ? AND order_id IS NULL", (cutoff,))
        cur = c.execute("UPDATE trades SET status='unknown', "
                        "rationale = rationale || ' | UNKNOWN: stale pending TTL' "
                        "WHERE status='pending' AND ts < ?", (cutoff,))
        return cur.rowcount


def void_trade(trade_id: int, reason: str) -> None:
    with _conn() as c:
        c.execute("UPDATE trades SET status='voided', rationale=rationale || ' | VOID: ' || ? "
                  "WHERE id=?", (reason, trade_id))


def has_open_position(ticker: str, mode: str | None = None) -> bool:
    # R3 5-reviewer consensus: 'unknown' MUST block re-entry — the order may have
    # filled, so trading the same ticker again can silently double real exposure
    q = "SELECT 1 FROM trades WHERE status IN ('open','pending','unknown') AND ticker=?"
    args: list = [ticker]
    if mode:
        q += " AND mode=?"
        args.append(mode)
    with _conn() as c:
        return c.execute(q, args).fetchone() is not None


def checkpoint() -> None:
    """R3-CODEX-2 HIGH fix: git ignores the -wal sidecar, so the pushed ledger.db
    could omit fills still sitting in WAL. Truncate-checkpoint before commits."""
    with _conn() as c:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")


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


def stats(mode: str | None = None) -> dict:
    """Risk usage. Paper and live keep SEPARATE budgets — pass mode to scope."""
    today = dt.date.today().isoformat()
    mc = " AND mode=?" if mode else ""
    ma: list = [mode] if mode else []
    with _conn() as c:
        risk_today = c.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM trades "
            f"WHERE ts LIKE ? || '%' AND status != 'voided'{mc}",
            [today] + ma).fetchone()[0]
        open_exp = c.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM trades "
            f"WHERE status IN ('open','pending','unknown'){mc}", ma).fetchone()[0]
        n_open = c.execute(
            f"SELECT COUNT(*) FROM trades WHERE status IN ('open','pending','unknown'){mc}",
            ma).fetchone()[0]
        pnl_today = c.execute(
            f"SELECT COALESCE(SUM(pnl_usd),0) FROM trades WHERE settled_ts LIKE ? || '%'{mc}",
            [today] + ma).fetchone()[0]
    return {"risk_used_today": risk_today, "open_exposure": open_exp,
            "open_positions": n_open, "realized_pnl_today": pnl_today}


def spent_today(prefixes: tuple, mode: str = "live") -> float:
    """Today's TOTAL cost on matching tickers regardless of status (settled included) —
    budget must not refill when positions resolve."""
    today = dt.date.today().isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT ticker, cost_usd FROM trades WHERE mode=? AND ts LIKE ? || '%' "
            "AND status != 'voided'", (mode, today)).fetchall()
    return round(sum(r["cost_usd"] for r in rows if r["ticker"].startswith(prefixes)), 2)


def spent_today_by_title(title_prefix: str, mode: str = "live") -> float:
    """Today's spend for ONE lane, keyed by title prefix — ticker prefixes collide
    across lanes (favorites and shortcycle both trade KXBTCD/KXETHD; bug #12)."""
    today = dt.date.today().isoformat()
    with _conn() as c:
        r = c.execute("SELECT COALESCE(SUM(cost_usd),0) FROM trades WHERE mode=? "
                      "AND ts LIKE ? || '%' AND status != 'voided' AND title LIKE ? || '%'",
                      (mode, today, title_prefix)).fetchone()
    return round(r[0], 2)


def realized_by_title(prefix: str) -> float:
    """Cumulative realized P&L of live trades whose title starts with prefix (lane tag)."""
    with _conn() as c:
        r = c.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM trades WHERE mode='live' "
                      "AND status IN ('settled','closed') AND title LIKE ? || '%'",
                      (prefix,)).fetchone()
    return round(r[0], 2)


def swing_summary() -> dict:
    with _conn() as c:
        r = c.execute("SELECT COUNT(*) n, COALESCE(SUM(pnl_usd),0) pnl "
                      "FROM trades WHERE status='closed'").fetchone()
    return {"n_closed": r["n"], "swing_pnl": round(r["pnl"], 2)}


def calibration() -> dict:
    """Brier scores answer: was the model actually better calibrated than the market?

    Favorites-lane trades are EXCLUDED: they record q_consensus = fill price by
    construction (structural-bias bet, no model estimate), so including them would
    dilute the model-vs-market comparison toward zero and corrupt the Sept-1 goal
    metric. Only trades with a genuine independent model probability count here.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT q_consensus, market_prob, side, result, pnl_usd FROM trades "
            "WHERE status='settled' AND result IN ('yes','no') "
            "AND (title IS NULL OR (title NOT LIKE 'favorite%' "
            "AND title NOT LIKE 'h10fav15m%' AND title NOT LIKE 'h15maker%' "
            "AND title NOT LIKE 'weather-fade%' "
            # R7 morning item: manual order-path tests (Alito #62) carry no
            # model probability — keep them out of the Sept-1 Brier track
            "AND title NOT LIKE 'manual%'))").fetchall()   # price-taking lanes
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
