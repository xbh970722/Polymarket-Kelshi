"""D1-EVENT: mechanical mispricing scanner + paper-only event-research book.

PAPER-ONLY. This module NEVER places a live order and NEVER writes the live
ledger. Its whole job is to answer, at ~$0 cost, whether the four-estimator
ensemble + fresh intel can price a single event above retail after fees.

print != fill: paper fills at the displayed order book. Real slippage and
partial-fill risk are not fully modeled. Everything here is D-class evidence
(mechanism only) and MUST NEVER feed the live edge gate. Promotion happens by
feeding the SAME research JSON to the battle-tested `pipeline decide` after the
pre-registered gate clears -- final ruling belongs to the main AI + user.

Money-path red line (consensus): no live/ledger imports, no order code, no
call into cmd_decide. The production ledger is only ever opened read-only via a
`file:...?mode=ro` URI, and only for the --legacy audit.

Consensus source: build_d1_spec.md v1.0 (Fable5 architect + codex5.6-sol),
gap245/build_d1_discussion.md (3 rounds), gap245/build_d1_design.md.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import yaml

from . import engine
from .kalshi_client import KalshiPublic, normalize_market, taker_fee_usd

# ---- paths (always relative Path("data")/...) ----
DB = Path("data") / "events.db"
SCAN_JSON = Path("data") / "events_scan.json"
BRIEF_JSON = Path("data") / "events_brief.json"
RESEARCH_DIR = Path("data") / "events_research"
LEDGER_DB = Path("data") / "ledger.db"

# ---- category priors (C5 consensus, code is the single source) ----
CATEGORY_W = {"Politics": 1.0, "Elections": 1.0,
              "Science and Technology": 0.7, "Companies": 0.7, "Entertainment": 0.7,
              "Economics": 0.5, "Financials": 0.5, "World": 0.5, "Commodities": 0.5}
# unknown categories -> 0.4; exclude_categories hard-drop before scoring

DOCTRINE = {
    "Sports": "announcements/procedure/eligibility/verifiable roster changes only; "
              "routine game outcomes are always no_trade",
    "Economics": "strong CME/nowcast benchmarks exist; only trade cross-benchmark "
                 "inconsistency or a breaking delay",
    "Financials": "same as Economics",
}

# ---- config defaults: single source of truth; the yaml block may be absent ----
DEFAULTS = {
    "scan": {
        "max_pages": 40,
        "min_volume_24h": 200,
        "min_open_interest": 300,
        "max_spread_cents": 8,
        "min_days_to_close": 0.25,
        "max_days_to_close": 30,
        "shortlist_size": 15,
        "max_per_category": 4,
        "exclude_categories": ["Crypto", "Climate and Weather", "Mentions"],
        "exclude_series_prefixes": ["KXBTC", "KXETH", "KXSOL", "KXXRP"],
    },
    "paper": {
        "bankroll_usd": 150,
        "kelly_fraction": 0.333,
        "max_per_trade_usd": 5.00,
        "min_edge_after_fees": 0.035,
        "consensus_max_divergence": 0.10,
        "max_open_positions": 10,
        "max_daily_risk_usd": 25,
        "daily_loss_halt_usd": 10,
        "max_total_exposure_usd": 60,
        "research_max_age_hours": 24,
    },
    "gate": {
        "min_settled_theses": 20,
        "min_net_pnl_usd": 0.0,
        "min_days": 14,
        "min_fill_ratio": 0.5,
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS escan(
  scan_run_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  ticker TEXT NOT NULL,
  event_ticker TEXT, category TEXT, title TEXT, subtitle TEXT,
  yes_bid REAL, yes_ask REAL, mid REAL, spread REAL,
  volume_24h REAL, open_interest REAL,
  close_time TEXT, d2c REAL,
  f_overround INTEGER DEFAULT 0,
  f_ladder INTEGER DEFAULT 0,
  f_longshot INTEGER DEFAULT 0,
  f_stale INTEGER DEFAULT 0,
  mp_score REAL,
  selected INTEGER DEFAULT 0,
  reject_reason TEXT,
  result TEXT,
  PRIMARY KEY (scan_run_id, ticker)
);
CREATE TABLE IF NOT EXISTS paper_trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  ticker TEXT NOT NULL, event_ticker TEXT, title TEXT, category TEXT,
  thesis_id TEXT NOT NULL,
  side TEXT NOT NULL,
  price REAL NOT NULL,
  top_ask REAL,
  contracts INTEGER NOT NULL,
  contracts_intended INTEGER,
  cost_usd REAL NOT NULL, fee_usd REAL NOT NULL,
  q_claude REAL, q_codex REAL, q_all TEXT,
  q_consensus REAL, market_prob REAL, edge_net REAL,
  book_summary TEXT,
  action TEXT,
  research_sha256 TEXT, research_file TEXT,
  rationale TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  result TEXT, pnl_usd REAL, settled_ts TEXT,
  close_time TEXT
);
CREATE TABLE IF NOT EXISTS marks(
  trade_id INTEGER NOT NULL,
  ts TEXT NOT NULL,
  sellable_bid REAL,
  PRIMARY KEY (trade_id, ts)
);
CREATE TABLE IF NOT EXISTS nav(
  d TEXT PRIMARY KEY,
  realized_pnl REAL, open_cost REAL, mtm_value REAL,
  nav REAL, n_open INTEGER, n_settled INTEGER
);
"""

FOOTER = ("print!=fill: paper fills at displayed book; real slippage/partial-fill "
          "risk not fully modeled - D-class evidence, never feeds the edge gate")

_NUM_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)")
_ABOVE_WORDS = ("or above", "or more", "or higher", "and above", "at least", ">=", ">", "≥")


# ---------------------------------------------------------------- helpers ----
def _cfg(cfg: dict) -> dict:
    """Two-level deep-merge of config['events'] onto DEFAULTS."""
    out = copy.deepcopy(DEFAULTS)
    ev = (cfg or {}).get("events") or {}
    for section, defaults in out.items():
        override = ev.get(section)
        if isinstance(override, dict):
            defaults.update(override)
    for section, val in ev.items():
        if section not in out:
            out[section] = val
    return out


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_iso(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _days_to_close(close_time, now):
    ct = _parse_iso(close_time)
    if ct is None:
        return None
    return (ct - now).total_seconds() / 86400.0


def _isprob(x) -> bool:
    return (isinstance(x, (int, float)) and not isinstance(x, bool)
            and x == x and 0.0 <= x <= 1.0)


def _norm_thesis(s) -> str:
    return "-".join((s or "").strip().lower().split())


def _load_config() -> dict:
    p = Path("config.yaml")
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


# ----------------------------------------------------------------- scan ------
def _strike(sub: str):
    """First numeric strike parsed from a subtitle, or None."""
    if not sub:
        return None
    m = _NUM_RE.search(str(sub).replace(",", "").replace("$", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _event_flags(mkts: list, mutually_exclusive: bool) -> list:
    """Event-level mechanical flags. `mkts` are normalized market dicts.

    overround (07-09 calibration): mutually_exclusive, all active, >=3 markets,
      and dev = sum(yes_mid) - 1.0 > max(0.08, sum(spread)/2). sum<1 never flags
      (mutually-exclusive != exhaustive; a low sum is 'no winner' probability).
    ladder: >=3 parseable strikes with a consistent direction word and an
      inverted P(>=low) < P(>=high) ordering. Ambiguous direction is skipped.
    """
    flags = []
    active = [m for m in mkts if m.get("status") == "active"]
    if mutually_exclusive and len(mkts) >= 3 and len(active) == len(mkts):
        mids = spreads = 0.0
        ok = True
        for m in mkts:
            yb = m.get("yes_bid") or 0.0
            ya = m.get("yes_ask") or 0.0
            if not (0.0 < ya <= 1.0 and 0.0 <= yb <= 1.0 and ya >= yb):
                ok = False
                break
            mids += (yb + ya) / 2.0
            spreads += (ya - yb)
        if ok and mids > 1.0 and (mids - 1.0) > max(0.08, spreads / 2.0):
            flags.append("overround")

    laddered = []
    for m in mkts:
        sub = m.get("yes_sub_title") or ""
        if any(w in sub.lower() for w in _ABOVE_WORDS):
            k = _strike(sub)
            ya = m.get("yes_ask") or 0.0
            yb = m.get("yes_bid") or 0.0
            if k is not None and ya > 0.0:
                laddered.append((k, (yb + ya) / 2.0))
    if len(laddered) >= 3:
        laddered.sort(key=lambda x: x[0])
        for i in range(len(laddered) - 1):
            if laddered[i][1] < laddered[i + 1][1] - 1e-9:
                flags.append("ladder")
                break
    return flags


def _score(m: dict, ev_flags: list, ecfg: dict):
    """Return (mp_score, flag_bools) for one normalized market dict."""
    yb = m.get("yes_bid") or 0.0
    ya = m.get("yes_ask") or 0.0
    mid = (yb + ya) / 2.0 if ya else 0.0
    last = m.get("last_price") or 0.0
    vol = m.get("volume_24h") or 0.0
    oi = m.get("open_interest") or 0.0
    spread_cents = max(0.0, ya - yb) * 100.0

    f_overround = 1 if "overround" in ev_flags else 0
    f_ladder = 1 if "ladder" in ev_flags else 0
    f_longshot = 1 if (0.03 <= mid <= 0.15 or 0.85 <= mid <= 0.97) else 0
    f_stale = 1 if (abs(last - mid) >= 0.05 and vol < 0.1 * oi) else 0

    score = (2.0 * f_overround + 1.5 * f_ladder + 1.0 * f_longshot + 1.5 * f_stale
             + min(math.log10(1.0 + vol) / 5.0, 1.0)
             - spread_cents * 0.05)
    score *= CATEGORY_W.get(m.get("category") or "", 0.4)
    flags = {"f_overround": f_overround, "f_ladder": f_ladder,
             "f_longshot": f_longshot, "f_stale": f_stale}
    return round(score, 4), flags


def scan(cfg: dict) -> list:
    """Sweep open events -> mechanical prefilter -> ranked shortlist.

    All hard-gate survivors are scored and persisted to escan (selected=0);
    event-dedupe + category-quota + rank truncation set reject_reason, the
    survivors are UPDATEd selected=1 and written to data/events_scan.json.
    """
    ec = _cfg(cfg)
    sc = ec["scan"]
    api = KalshiPublic()
    now = _now_utc()
    run_id = now.isoformat(timespec="seconds")
    excl_cats = set(sc["exclude_categories"])
    excl_pfx = tuple(sc["exclude_series_prefixes"])

    rows = []
    categories_seen = {}
    n_swept = 0
    for ev in api.iter_events(status="open", max_pages=sc["max_pages"]):
        cat = ev.get("category") or ""
        categories_seen[cat] = categories_seen.get(cat, 0) + 1
        et = ev.get("event_ticker")
        me = bool(ev.get("mutually_exclusive"))
        norm = []
        for mr in ev.get("markets") or []:
            nm = normalize_market(mr)
            nm["category"] = cat
            nm["yes_sub_title"] = mr.get("yes_sub_title")
            norm.append(nm)
        ev_flags = _event_flags(norm, me)
        for nm in norm:
            n_swept += 1
            tk = nm.get("ticker") or ""
            if cat in excl_cats or tk.startswith(excl_pfx):
                continue
            if nm.get("status") != "active":
                continue
            yb = nm.get("yes_bid") or 0.0
            ya = nm.get("yes_ask") or 0.0
            if not (0.0 < ya <= 1.0 and 0.0 <= yb <= 1.0 and ya >= yb):
                continue
            mid = (yb + ya) / 2.0
            spread = ya - yb
            vol = nm.get("volume_24h") or 0.0
            oi = nm.get("open_interest") or 0.0
            d2c = _days_to_close(nm.get("close_time"), now)
            # hard gate: vol / OI / spread / mid 4-96c / d2c
            if vol < sc["min_volume_24h"]:
                continue
            if oi < sc["min_open_interest"]:
                continue
            if spread * 100.0 > sc["max_spread_cents"]:
                continue
            if not (0.04 <= mid <= 0.96):
                continue
            if d2c is None or not (sc["min_days_to_close"] <= d2c <= sc["max_days_to_close"]):
                continue
            mp_score, flags = _score(nm, ev_flags, ec)
            rows.append({
                "ticker": tk, "event_ticker": et, "category": cat,
                "title": nm.get("title"), "subtitle": nm.get("yes_sub_title"),
                "yes_bid": yb, "yes_ask": ya, "mid": round(mid, 4),
                "spread": round(spread, 4), "volume_24h": vol, "open_interest": oi,
                "close_time": nm.get("close_time"),
                "d2c": round(d2c, 3), "flags": flags, "mp_score": mp_score,
                "ev_flag_list": ev_flags, "selected": 0, "reject_reason": None,
            })

    rows.sort(key=lambda r: r["mp_score"], reverse=True)
    # event dedupe (<=2 per event)
    per_event = {}
    survivors = []
    for r in rows:
        et = r["event_ticker"]
        if per_event.get(et, 0) >= 2:
            r["reject_reason"] = "event_dedupe"
            continue
        per_event[et] = per_event.get(et, 0) + 1
        survivors.append(r)
    # category quota
    per_cat = {}
    after_quota = []
    for r in survivors:
        c = r["category"]
        if per_cat.get(c, 0) >= sc["max_per_category"]:
            r["reject_reason"] = "category_quota"
            continue
        per_cat[c] = per_cat.get(c, 0) + 1
        after_quota.append(r)
    # rank truncation
    shortlist = after_quota[:sc["shortlist_size"]]
    for r in after_quota[sc["shortlist_size"]:]:
        r["reject_reason"] = "rank"
    for r in shortlist:
        r["selected"] = 1

    with _conn() as c:
        for r in rows:
            fb = r["flags"]
            c.execute(
                "INSERT OR REPLACE INTO escan(scan_run_id, ts, ticker, event_ticker,"
                " category, title, subtitle, yes_bid, yes_ask, mid, spread,"
                " volume_24h, open_interest, close_time, d2c, f_overround, f_ladder,"
                " f_longshot, f_stale, mp_score, selected, reject_reason)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, run_id, r["ticker"], r["event_ticker"], r["category"],
                 r["title"], r["subtitle"], r["yes_bid"], r["yes_ask"], r["mid"],
                 r["spread"], r["volume_24h"], r["open_interest"], r["close_time"],
                 r["d2c"], fb["f_overround"], fb["f_ladder"], fb["f_longshot"],
                 fb["f_stale"], r["mp_score"], r["selected"], r["reject_reason"]))

    out = {
        "generated": run_id,
        "scan_run_id": run_id,
        "categories_seen": categories_seen,
        "n_swept": n_swept,
        "n_gated": len(rows),
        "candidates": [{
            "ticker": r["ticker"], "event_ticker": r["event_ticker"],
            "category": r["category"], "title": r["title"], "subtitle": r["subtitle"],
            "mid": r["mid"], "spread": r["spread"], "volume_24h": r["volume_24h"],
            "open_interest": r["open_interest"], "d2c": r["d2c"],
            "mp_score": r["mp_score"], "flags": r["ev_flag_list"],
        } for r in shortlist],
    }
    SCAN_JSON.parent.mkdir(exist_ok=True)
    SCAN_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return shortlist


# ----------------------------------------------------------------- brief -----
def top_tickers(n: int) -> list:
    """First n tickers from the last scan shortlist (empty if none)."""
    if not SCAN_JSON.exists():
        return []
    try:
        sj = json.loads(SCAN_JSON.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return [c["ticker"] for c in (sj.get("candidates") or [])[:n]]


def _scan_category_map() -> dict:
    if not SCAN_JSON.exists():
        return {}
    try:
        sj = json.loads(SCAN_JSON.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return {c["ticker"]: c.get("category") for c in (sj.get("candidates") or [])}


def _latest_escan(ticker: str):
    with _conn() as c:
        r = c.execute(
            "SELECT f_overround, f_ladder, f_longshot, f_stale, mp_score FROM escan"
            " WHERE ticker=? ORDER BY scan_run_id DESC LIMIT 1", (ticker,)).fetchone()
    if not r:
        return [], None
    flags = [name[2:] for name in ("f_overround", "f_ladder", "f_longshot", "f_stale")
             if r[name]]
    return flags, r["mp_score"]


def brief(cfg: dict, tickers: list) -> dict:
    """Standardized four-model input. The `blind` segment carries NO prices:
    the blind protocol becomes a data-shape discipline, not a prompt rule."""
    api = KalshiPublic()
    cat_map = _scan_category_map()
    out = {}
    for t in tickers:
        try:
            m = api.market(t)
        except Exception as e:                       # noqa: BLE001 - one bad ticker must not sink the batch
            out[t] = {"error": f"market fetch failed: {e}"}
            continue
        nm = normalize_market(m)
        et = m.get("event_ticker")
        cat = cat_map.get(t)
        if not cat and et:
            try:
                cat = (api._get(f"/events/{et}").get("event") or {}).get("category")
            except Exception:                        # noqa: BLE001
                cat = None
        cat = cat or ""

        sib_titles, sib_mids = [], []
        if et:
            try:
                sp = api._get("/markets", event_ticker=et)
                for smr in sp.get("markets") or []:
                    if smr.get("ticker") == t:
                        continue
                    snm = normalize_market(smr)
                    sib_titles.append(snm.get("yes_sub_title") or snm.get("title")
                                      or smr.get("ticker"))
                    sib_mids.append(round((snm["yes_bid"] + snm["yes_ask"]) / 2.0, 4)
                                    if snm["yes_ask"] else None)
            except Exception:                        # noqa: BLE001
                pass

        mp_flags, mp_score = _latest_escan(t)
        mid = round((nm["yes_bid"] + nm["yes_ask"]) / 2.0, 4) if nm["yes_ask"] else 0.0
        out[t] = {
            "blind": {
                "ticker": t, "title": nm.get("title"),
                "subtitle": nm.get("yes_sub_title"),
                "rules_primary": m.get("rules_primary"),
                "rules_secondary": m.get("rules_secondary"),
                "close_time": nm.get("close_time"), "category": cat,
                "doctrine": DOCTRINE.get(cat, ""), "sibling_titles": sib_titles,
            },
            "arbiter": {
                "yes_bid": nm["yes_bid"], "yes_ask": nm["yes_ask"], "mid": mid,
                "volume_24h": nm["volume_24h"], "oi": nm["open_interest"],
                "sibling_mids": sib_mids, "mp_flags": mp_flags, "mp_score": mp_score,
            },
        }
    BRIEF_JSON.parent.mkdir(exist_ok=True)
    BRIEF_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


# ------------------------------------------------------------- order book ----
def _book_for_buy(api, ticker: str, side: str) -> list:
    """Buy-side cost ladder [(cost_px, qty), ...] ascending by cost.

    orderbook_fp holds BID arrays. Buying YES consumes NO bids (cost = 1-no_px);
    buying NO consumes YES bids (cost = 1-yes_px). Any parse failure returns []
    (caller falls back to top-ask booking and notes 'book_unavailable').
    """
    try:
        resp = api._get(f"/markets/{ticker}/orderbook")
    except Exception:                                # noqa: BLE001
        return []
    fp = resp.get("orderbook_fp") or {}
    arr = fp.get("no_dollars") if side == "yes" else fp.get("yes_dollars")
    if not arr:
        return []
    levels = []
    for pair in arr:
        try:
            px = float(pair[0])
            qty = float(pair[1])
        except (ValueError, IndexError, TypeError):
            continue
        cost = 1.0 - px
        if 0.0 < cost < 1.0 and qty > 0:
            levels.append((round(cost, 4), qty))
    levels.sort(key=lambda x: x[0])
    return levels


def _vwap_fill(levels: list, n: int):
    """Walk the ladder filling up to n contracts -> (vwap, filled, consumed)."""
    remaining, filled, spend = n, 0, 0.0
    consumed = []
    for cost, qty in levels:
        if remaining <= 0:
            break
        take = min(remaining, int(qty))
        if take <= 0:
            continue
        spend += take * cost
        filled += take
        remaining -= take
        consumed.append([cost, take])
    vwap = round(spend / filled, 4) if filled else 0.0
    return vwap, filled, consumed


# --------------------------------------------------------------- decide ------
def _paper_stats() -> dict:
    """ledger.stats-shaped snapshot computed from events.db (for check_risk)."""
    today = _now_utc().date().isoformat()
    realized = risk = exposure = 0.0
    n_open = 0
    with _conn() as c:
        for r in c.execute("SELECT ts, settled_ts, cost_usd, pnl_usd, status"
                           " FROM paper_trades"):
            if (r["ts"] or "")[:10] == today:
                risk += r["cost_usd"] or 0.0
            if r["status"] == "settled" and (r["settled_ts"] or "")[:10] == today:
                realized += r["pnl_usd"] or 0.0
            if r["status"] == "open":
                exposure += r["cost_usd"] or 0.0
                n_open += 1
    return {"realized_pnl_today": round(realized, 4),
            "risk_used_today": round(risk, 4),
            "open_exposure": round(exposure, 4),
            "open_positions": n_open}


def _overlay(cfg: dict, ec: dict) -> dict:
    """Deep-copy cfg and overwrite sizing/risk/edge with events.paper values."""
    pc = ec["paper"]
    ov = copy.deepcopy(cfg) if cfg else {}
    ov["sizing"] = {"bankroll_usd": pc["bankroll_usd"],
                    "kelly_fraction": pc["kelly_fraction"]}
    ov["risk"] = {"max_per_trade_usd": pc["max_per_trade_usd"],
                  "max_daily_risk_usd": pc["max_daily_risk_usd"],
                  "max_total_exposure_usd": pc["max_total_exposure_usd"],
                  "max_open_positions": pc["max_open_positions"],
                  "daily_loss_halt_usd": pc["daily_loss_halt_usd"]}
    ov["edge"] = {"min_edge_after_fees": pc["min_edge_after_fees"],
                  "consensus_max_divergence": pc["consensus_max_divergence"]}
    return ov


def _has_open(ticker: str, thesis: str) -> bool:
    with _conn() as c:
        r = c.execute("SELECT COUNT(*) n FROM paper_trades WHERE status='open'"
                      " AND (ticker=? OR thesis_id=?)", (ticker, thesis)).fetchone()
    return bool(r and r["n"] > 0)


def _reentry_blocked(ticker: str, thesis: str, item: dict, file_sha: str):
    """C3 reentry gate. A prior realized loss on same ticker OR thesis requires
    material_evidence_delta + non-empty delta_note + a prior_research_sha256 that
    differs from this file. Ledger check is ticker-only (no thesis column) and
    read-only; failure degrades to paper-only with a warning."""
    prior_loss = False
    with _conn() as c:
        r = c.execute("SELECT COUNT(*) n FROM paper_trades WHERE pnl_usd < 0"
                      " AND (ticker=? OR thesis_id=?)", (ticker, thesis)).fetchone()
        if r and r["n"] > 0:
            prior_loss = True
    if not prior_loss and LEDGER_DB.exists():
        try:
            lc = sqlite3.connect(f"file:{LEDGER_DB}?mode=ro", uri=True)
            try:
                r = lc.execute("SELECT COUNT(*) FROM trades WHERE"
                               " status IN ('settled','closed') AND pnl_usd < 0"
                               " AND ticker=?", (ticker,)).fetchone()
                if r and r[0] > 0:
                    prior_loss = True
            finally:
                lc.close()
        except sqlite3.Error as e:
            print(f"WARN reentry: production ledger read failed ({e}); paper-only check")
    if not prior_loss:
        return None
    med = item.get("material_evidence_delta") is True
    dn = (item.get("delta_note") or "").strip()
    psha = (item.get("prior_research_sha256") or "").strip()
    if med and dn and psha and psha != file_sha:
        return None
    return "reentry_blocked_same_thesis"


def decide_paper(cfg: dict, research_path: str) -> None:
    """Read research JSON -> fail-closed validation chain -> engine.decide +
    check_risk (100% reused) -> depth-adjusted VWAP fill -> paper_trades."""
    ec = _cfg(cfg)
    pc = ec["paper"]
    path = Path(research_path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        print(f"SKIP file: cannot read research ({e})")
        return
    file_sha = hashlib.sha256(raw).hexdigest()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        print(f"SKIP file: cannot parse research JSON ({e})")
        return
    if doc.get("schema") != "d1-research-v2":
        print(f"SKIP file: schema != d1-research-v2 (got {doc.get('schema')!r})")
        return

    api = KalshiPublic()
    cfg_ov = _overlay(cfg, ec)
    placed = skipped = 0
    for item in doc.get("items") or []:
        ticker = item.get("ticker")
        tag = ticker or "?"
        if item.get("recommended_action") != "trade":
            print(f"SKIP {tag}: recommended_action={item.get('recommended_action')!r} (not trade)")
            skipped += 1
            continue
        if (item.get("arbiter") or {}).get("veto"):
            print(f"SKIP {tag}: arbiter veto ({(item.get('arbiter') or {}).get('reason', '')})")
            skipped += 1
            continue
        qc, qx = item.get("q_claude"), item.get("q_codex")
        if not (_isprob(qc) and _isprob(qx)):
            print(f"SKIP {tag}: q_claude/q_codex out of [0,1]")
            skipped += 1
            continue
        q_all = item.get("q_all")
        if not (isinstance(q_all, list) and len(q_all) == 4 and all(_isprob(x) for x in q_all)):
            print(f"SKIP {tag}: q_all must be a length-4 array in [0,1]")
            skipped += 1
            continue
        asof = _parse_iso(item.get("asof"))
        if asof is None:
            print(f"SKIP {tag}: asof unparseable")
            skipped += 1
            continue
        age_h = (_now_utc() - asof).total_seconds() / 3600.0
        if age_h > pc["research_max_age_hours"]:
            print(f"SKIP {tag}: research asof {age_h:.1f}h exceeds max {pc['research_max_age_hours']}h")
            skipped += 1
            continue
        thesis = _norm_thesis(item.get("thesis_id"))
        if not thesis:
            print(f"SKIP {tag}: missing thesis_id")
            skipped += 1
            continue
        blocked = _reentry_blocked(ticker, thesis, item, file_sha)
        if blocked:
            print(f"SKIP {tag}: {blocked}")
            skipped += 1
            continue
        if _has_open(ticker, thesis):
            print(f"SKIP {tag}: already holding an open paper position on same ticker/thesis")
            skipped += 1
            continue

        try:
            mn = api.market_norm(ticker)
        except Exception as e:                       # noqa: BLE001
            print(f"SKIP {tag}: market fetch failed ({e})")
            skipped += 1
            continue
        ya, na, yb = mn["yes_ask"], mn["no_ask"], mn["yes_bid"]
        if not (0.01 <= ya <= 0.99 and 0.01 <= na <= 0.99):
            print(f"SKIP {tag}: no live two-sided quote")
            skipped += 1
            continue
        d = engine.decide(qc, qx, ya, na, cfg_ov)
        if d.action == "skip":
            print(f"SKIP {tag}: {d.reason}")
            skipped += 1
            continue
        veto = engine.check_risk(_paper_stats(), d.cost_usd, cfg_ov)
        if veto:
            print(f"VETO {tag}: {veto}")
            skipped += 1
            continue

        levels = _book_for_buy(api, ticker, d.side)
        if levels:
            vwap, filled, consumed = _vwap_fill(levels, d.contracts)
            book_summary = json.dumps({"consumed": consumed,
                                       "quote_asof": _now_utc().isoformat(timespec="seconds")})
        else:
            vwap, filled, consumed = d.price, d.contracts, []
            book_summary = json.dumps({"book_unavailable": True,
                                       "quote_asof": _now_utc().isoformat(timespec="seconds")})
        n_eff = min(d.contracts, filled)
        if n_eff < 1:
            print(f"SKIP {tag}: no book depth to fill")
            skipped += 1
            continue
        q_side = d.q_consensus if d.side == "yes" else 1.0 - d.q_consensus
        edge_v = q_side - vwap - taker_fee_usd(vwap, 1)
        if edge_v < pc["min_edge_after_fees"]:
            print(f"SKIP {tag}: depth-adjusted edge {edge_v:+.3f} below threshold {pc['min_edge_after_fees']}")
            skipped += 1
            continue

        fee = taker_fee_usd(vwap, n_eff)
        cost = round(n_eff * vwap + fee, 2)
        market_prob = round((yb + ya) / 2.0, 4) if yb else round(ya, 4)
        now_iso = _now_utc().isoformat(timespec="seconds")
        with _conn() as c:
            c.execute(
                "INSERT INTO paper_trades(ts, ticker, event_ticker, title, category,"
                " thesis_id, side, price, top_ask, contracts, contracts_intended,"
                " cost_usd, fee_usd, q_claude, q_codex, q_all, q_consensus,"
                " market_prob, edge_net, book_summary, action, research_sha256,"
                " research_file, rationale, status, close_time)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now_iso, ticker, item.get("event_ticker"), item.get("title"),
                 item.get("category_override") or item.get("category"), thesis,
                 d.side, vwap, d.price, n_eff, d.contracts, cost, fee, qc, qx,
                 json.dumps(q_all), d.q_consensus, market_prob, round(edge_v, 4),
                 book_summary, item.get("recommended_action"), file_sha, path.name,
                 item.get("rationale"), "open", item.get("close_time")))
        _archive(path, file_sha)
        placed += 1
        fill_ratio = n_eff / d.contracts if d.contracts else 1.0
        min_fill = ec["gate"]["min_fill_ratio"]
        dust = f" DUST(fill_ratio={fill_ratio:.2f}<{min_fill})" if fill_ratio < min_fill else ""
        print(f"PAPER-EVENT {tag}: {d.side.upper()} {n_eff}@{vwap:.3f} cost=${cost:.2f}"
              f" edge={edge_v:+.3f} thesis={thesis} [intended {d.contracts}]{dust}")

    print(f"paper decide: {placed} placed, {skipped} skipped")
    print(FOOTER)


def _archive(path: Path, file_sha: str) -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    dest = RESEARCH_DIR / f"{file_sha[:8]}_{_now_utc().date().isoformat()}.json"
    if not dest.exists():
        try:
            shutil.copy2(path, dest)
        except OSError:
            pass


# --------------------------------------------------------------- settle ------
def settle(cfg: dict):
    """Settle resolved open positions, mark still-active ones, snapshot NAV.

    v1 discipline: paper holds to settlement (no swing exit). Swing behaviour is
    reconstructed counterfactually from the marks series inside report()."""
    api = KalshiPublic()
    now = _now_utc()
    now_iso = now.isoformat(timespec="seconds")
    n_settled = n_marked = 0
    pnl_delta = 0.0
    with _conn() as c:
        opens = c.execute("SELECT * FROM paper_trades WHERE status='open'").fetchall()
        for r in opens:
            tk = r["ticker"]
            try:
                mk = api.market(tk)
            except Exception:                        # noqa: BLE001
                continue
            st = mk.get("status")
            res = mk.get("result")
            if st in ("settled", "finalized") and res in ("yes", "no"):
                win = 1.0 if res == r["side"] else 0.0
                pnl = round(r["contracts"] * win - r["cost_usd"], 4)
                c.execute("UPDATE paper_trades SET status='settled', result=?,"
                          " pnl_usd=?, settled_ts=? WHERE id=?",
                          (res, pnl, now_iso, r["id"]))
                c.execute("UPDATE escan SET result=? WHERE ticker=?", (res, tk))
                n_settled += 1
                pnl_delta += pnl
            elif st in ("settled", "finalized"):
                # finalized but non-binary result -> voided (refund semantics)
                c.execute("UPDATE paper_trades SET status='voided', result=?,"
                          " pnl_usd=0, settled_ts=? WHERE id=?",
                          (res or "void", now_iso, r["id"]))
                n_settled += 1
            else:
                mn = normalize_market(mk)
                bid = mn["yes_bid"] if r["side"] == "yes" else mn["no_bid"]
                c.execute("INSERT OR IGNORE INTO marks(trade_id, ts, sellable_bid)"
                          " VALUES (?,?,?)", (r["id"], now_iso, bid))
                n_marked += 1
        _nav_snapshot(c, cfg, now)
    return n_settled, n_marked, round(pnl_delta, 4)


def _nav_snapshot(c: sqlite3.Connection, cfg: dict, now: dt.datetime) -> None:
    bankroll = _cfg(cfg)["paper"]["bankroll_usd"]
    realized = sum((r["pnl_usd"] or 0.0) for r in
                   c.execute("SELECT pnl_usd FROM paper_trades WHERE status='settled'"))
    open_cost = mtm = 0.0
    n_open = 0
    for r in c.execute("SELECT id, price, contracts, cost_usd FROM paper_trades"
                       " WHERE status='open'"):
        open_cost += r["cost_usd"] or 0.0
        n_open += 1
        mk = c.execute("SELECT sellable_bid FROM marks WHERE trade_id=?"
                       " ORDER BY ts DESC LIMIT 1", (r["id"],)).fetchone()
        # No mark row yet (e.g. a transient market() fetch failure skipped this
        # ticker's mark this round) -> unknown liquidation value defaults to 0,
        # never to entry price (that would overstate NAV; a genuine zero bid is
        # already stored as a real 0.0 row and handled by the branch above).
        bid = mk["sellable_bid"] if (mk and mk["sellable_bid"] is not None) else 0.0
        mtm += bid * r["contracts"]
    n_settled = c.execute("SELECT COUNT(*) n FROM paper_trades"
                          " WHERE status='settled'").fetchone()["n"]
    nav = bankroll + realized + (mtm - open_cost)
    c.execute("INSERT OR REPLACE INTO nav(d, realized_pnl, open_cost, mtm_value,"
              " nav, n_open, n_settled) VALUES (?,?,?,?,?,?,?)",
              (now.date().isoformat(), round(realized, 4), round(open_cost, 4),
               round(mtm, 4), round(nav, 4), n_open, n_settled))


# --------------------------------------------------------------- report ------
def _is_dust(r, min_fill: float) -> bool:
    ci = r["contracts_intended"] or r["contracts"]
    if not ci:
        return False
    return (r["contracts"] / ci) < min_fill


def _max_dd(navs) -> float:
    peak = None
    mdd = 0.0
    for row in navs:
        v = row["nav"]
        if v is None:
            continue
        if peak is None or v > peak:
            peak = v
        mdd = max(mdd, peak - v)
    return round(mdd, 4)


def _summary(rows, label: str) -> None:
    n = len(rows)
    wins = sum(1 for r in rows if (r["pnl_usd"] or 0.0) > 0)
    pnl = sum((r["pnl_usd"] or 0.0) for r in rows)
    fees = sum((r["fee_usd"] or 0.0) for r in rows)
    theses = len({r["thesis_id"] for r in rows})
    wr = (wins / n * 100.0) if n else 0.0
    print(f"[{label}] n={n} theses={theses} win_rate={wr:.1f}%"
          f" net_pnl=${pnl:+.2f} fees=${fees:.2f}")


def report(cfg: dict, legacy: bool = False) -> None:
    if legacy:
        _legacy_report()
        return
    ec = _cfg(cfg)
    gate = ec["gate"]
    with _conn() as c:
        settled = c.execute("SELECT * FROM paper_trades WHERE status='settled'").fetchall()
        opens = c.execute("SELECT * FROM paper_trades WHERE status='open'").fetchall()
        navs = c.execute("SELECT * FROM nav ORDER BY d").fetchall()

        print("=== D1-EVENT PAPER REPORT (paper-only, D-class) ===")
        _summary(settled, "ALL settled")
        _summary([r for r in settled if (r["edge_net"] or 0.0) >= 0.05],
                 "edge>=0.05 subset")

        # NAV tail + max drawdown
        print(f"-- NAV (last {min(10, len(navs))} of {len(navs)}; max_dd=${_max_dd(navs):.2f}) --")
        for row in navs[-10:]:
            print(f"  {row['d']} nav=${row['nav']:.2f} realized=${row['realized_pnl']:+.2f}"
                  f" mtm=${row['mtm_value']:.2f} open={row['n_open']} settled={row['n_settled']}")

        # category x flag attribution
        cat_pnl = {}
        for r in settled:
            k = r["category"] or "Other"
            cat_pnl[k] = cat_pnl.get(k, 0.0) + (r["pnl_usd"] or 0.0)
        if cat_pnl:
            print("-- by category --")
            for k in sorted(cat_pnl):
                print(f"  {k:<26} ${cat_pnl[k]:+.2f}")
        flag_pnl = {"overround": 0.0, "ladder": 0.0, "longshot": 0.0,
                    "stale": 0.0, "none": 0.0}
        for r in settled:
            er = c.execute("SELECT f_overround, f_ladder, f_longshot, f_stale FROM escan"
                           " WHERE ticker=? ORDER BY scan_run_id DESC LIMIT 1",
                           (r["ticker"],)).fetchone()
            pnl = r["pnl_usd"] or 0.0
            hit = False
            if er:
                for name in ("f_overround", "f_ladder", "f_longshot", "f_stale"):
                    if er[name]:
                        flag_pnl[name[2:]] += pnl
                        hit = True
            if not hit:
                flag_pnl["none"] += pnl
        print("-- by mechanical flag --")
        for k in ("overround", "ladder", "longshot", "stale", "none"):
            print(f"  {k:<10} ${flag_pnl[k]:+.2f}")

        # expected edge vs realized
        exp_edge = (sum((r["edge_net"] or 0.0) for r in settled) / len(settled)
                    if settled else 0.0)
        tot_cost = sum((r["cost_usd"] or 0.0) for r in settled)
        tot_pnl = sum((r["pnl_usd"] or 0.0) for r in settled)
        realized_ret = (tot_pnl / tot_cost) if tot_cost else 0.0
        print(f"-- expected vs realized -- avg_edge_net={exp_edge:+.3f}"
              f" realized_return={realized_ret:+.3f} (pnl/cost)")

        # swing counterfactual (sampled-marks-only)
        tp = sl = held = 0
        for r in settled + list(opens):
            qs = r["q_consensus"] or 0.0
            q_side = qs if r["side"] == "yes" else 1.0 - qs
            plan = engine.plan_exit(q_side, r["price"], cfg or {})
            fired = None
            for mk in c.execute("SELECT sellable_bid FROM marks WHERE trade_id=?"
                                " ORDER BY ts", (r["id"],)):
                kind, _ = engine.check_exit(plan.target_price, plan.stop_price,
                                            mk["sellable_bid"] or 0.0)
                if kind:
                    fired = kind
                    break
            if fired == "take_profit":
                tp += 1
            elif fired == "stop_loss":
                sl += 1
            else:
                held += 1
        print(f"-- swing counterfactual (sampled-marks-only) -- take_profit={tp}"
              f" stop_loss={sl} held={held}")

    # dust + gate
    min_fill = gate["min_fill_ratio"]
    dust = [r for r in settled if _is_dust(r, min_fill)]
    non_dust = [r for r in settled if not _is_dust(r, min_fill)]
    if dust:
        print(f"-- DUST (fill_ratio<{min_fill}, excluded from gate thesis count),"
              f" n={len(dust)} --")
        for r in dust:
            print(f"  {r['ticker']} fill={r['contracts']}/{r['contracts_intended']}"
                  f" pnl=${r['pnl_usd'] or 0.0:+.2f}")

    gate_theses = len({r["thesis_id"] for r in non_dust})
    net_pnl = sum((r["pnl_usd"] or 0.0) for r in settled)
    first_ts = min((r["ts"] for r in (list(settled) + list(opens))), default=None)
    days = 0
    ft = _parse_iso(first_ts)
    if ft:
        days = (_now_utc() - ft).days

    def light(ok):
        return "PASS" if ok else "wait"
    print("-- PROMOTION GATE (pre-registered proposal; final ruling = main AI + user) --")
    print(f"  [{light(gate_theses >= gate['min_settled_theses'])}]"
          f" non-dust independent theses {gate_theses}/{gate['min_settled_theses']}")
    print(f"  [{light(net_pnl > gate['min_net_pnl_usd'])}]"
          f" net P&L ${net_pnl:+.2f} > ${gate['min_net_pnl_usd']:.2f}")
    print(f"  [{light(days >= gate['min_days'])}]"
          f" days since first trade {days}/{gate['min_days']}")


_LEGACY_CAT = [
    ("Science and Technology", ("GPT", "LLM", "OPENAI", "OPENB", "AGI")),
    ("Politics", ("ALITO", "TRUMP", "PLATNER", "MEDNOM", "SCOTUS", "SENATE",
                  "GOVERNOR", "ELECTION", "NOM", "CONGRESS", "PRES", "GOP")),
    ("Entertainment", ("SONG", "RANKLIST", "RT-", "ODY", "ROTTEN", "OSCAR",
                       "BOXOFFICE", "MOVIE", "ALBUM", "BILLBOARD", "GRAMMY")),
    ("Economics", ("FED", "CPI", "GDP", "JOBS", "RATE", "FOMC", "PCE", "NFP")),
]


def _legacy_category(ticker: str, title: str) -> str:
    t = (ticker or "").upper()
    for cat, kws in _LEGACY_CAT:
        if any(k in t for k in kws):
            return cat
    return "Other"


def _legacy_report() -> None:
    """Reconstruct the 07-09 dual-seat live event-book audit from the production
    ledger, opened strictly read-only (mode=ro). No ledger module import."""
    if not LEDGER_DB.exists():
        print("legacy: data/ledger.db not found")
        return
    title_pfx = ("favorite", "shortcycle", "weather", "h10fav15m", "h15maker", "manual")
    tick_pfx = ("KXBTC", "KXETH", "KXSOL", "KXXRP", "KXHIGH")
    c = sqlite3.connect(f"file:{LEDGER_DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT ticker, title, side, cost_usd, pnl_usd, status, result"
                     " FROM trades WHERE mode='live'").fetchall()
    c.close()

    def excluded(r):
        t = (r["title"] or "").lower()
        if any(t.startswith(p) for p in title_pfx):
            return True
        return any((r["ticker"] or "").startswith(p) for p in tick_pfx)

    ev = [r for r in rows if not excluded(r)]
    settled = [r for r in ev if r["status"] in ("settled", "closed")]
    opens = [r for r in ev if r["status"] == "open"]
    tot_pnl = sum((r["pnl_usd"] or 0.0) for r in settled)
    tot_cost = sum((r["cost_usd"] or 0.0) for r in settled)
    binary = sum(1 for r in settled if r["result"] in ("yes", "no"))
    print("=== LEGACY LIVE EVENT-BOOK AUDIT (ledger.db, mode=ro) ===")
    print(f"settled/closed events: n={len(settled)} net_pnl=${tot_pnl:+.2f}"
          f" cost=${tot_cost:.2f} binary_settled={binary}")
    catp = {}
    for r in settled:
        k = _legacy_category(r["ticker"], r["title"])
        catp[k] = catp.get(k, 0.0) + (r["pnl_usd"] or 0.0)
    for k in sorted(catp):
        print(f"  {k:<26} ${catp[k]:+.2f}")
    print(f"open events: n={len(opens)} cost=${sum((r['cost_usd'] or 0.0) for r in opens):.2f}")


# ------------------------------------------------------------------ CLI ------
def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="events")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    pb = sub.add_parser("brief")
    pb.add_argument("--tickers", default="")
    pb.add_argument("--top", type=int, default=3)
    pd = sub.add_parser("decide")
    pd.add_argument("--research", required=True)
    sub.add_parser("settle")
    pr = sub.add_parser("report")
    pr.add_argument("--legacy", action="store_true")
    args = ap.parse_args()
    cfg = _load_config()

    if args.cmd == "scan":
        rows = scan(cfg)
        print(f"scan: {len(rows)} shortlisted -> data/events_scan.json")
        for r in rows:
            flags = ",".join(r.get("ev_flag_list") or []) or "-"
            print(f"  {r['mp_score']:6.3f} {(r['ticker'] or '')[:40]:<40}"
                  f" mid={r['mid']:.2f} {flags}")
    elif args.cmd == "brief":
        tickers = ([t.strip() for t in args.tickers.split(",") if t.strip()]
                   if args.tickers.strip() else top_tickers(args.top))
        b = brief(cfg, tickers)
        print(f"brief: {len(b)} tickers -> data/events_brief.json")
    elif args.cmd == "decide":
        decide_paper(cfg, args.research)
    elif args.cmd == "settle":
        ns, nm, pnl = settle(cfg)
        print(f"settle: {ns} settled, {nm} marked, pnl_delta=${pnl:+.2f}")
    elif args.cmd == "report":
        report(cfg, legacy=args.legacy)


if __name__ == "__main__":
    main()
