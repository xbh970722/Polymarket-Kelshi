r"""H16 埋伏单 quote 影子记录器 (D3-CRYPTO-STRUCTURAL, build_d3_spec §3).

FREEZE-14 research-only. venue='production', execution_mode='quote_proxy'.
本模块只记录/回放生产 quote 影子, 零订单能力, 不接 pipeline/live。写入面唯一是
data/h16_shadow.db; tick 分区永远只读经 src.tickstore。联网只两类公共只读 GET:
Kalshi 公共 market()(结算) 与 Coinbase 公共 candles(acquisition phase, 判定路径
永不同步发 REST)。当前库只有 top-3 quote + last_trade_px ⇒ 一切 fill 都是
QUOTE_PROXY_ONLY 上界, 绝非 confirmed maker fill; G0 门规定 quote proxy 永不单独 GO。

import allowlist: stdlib + src.tickstore + src.kalshi_client(KalshiPublic) +
src.shortcycle(strike_of)。禁 order-capable client。
"""
import datetime as dt
import hashlib
import json
import math
import random
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from .kalshi_client import KalshiPublic
from .shortcycle import strike_of
from .tickstore import TickStore, iso_to_ms, ms_to_iso

# holding_quote (§3.2: the ONE side/price换算 point) lives in THIS module; tickstore
# stays venue-agnostic. Never scatter hand-written 1000-x elsewhere.

VENUE = "production"
EXECUTION_MODE = "quote_proxy"
DB = Path("data") / "h16_shadow.db"
ET = ZoneInfo("America/New_York")
_UTC = dt.timezone.utc
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=_UTC)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}

# --------------------------------------------------------------------------- #
# 冻结 manifest v2 (参数唯一权威 = gap245/build_d3_design.md JSON + R3 patch)
# --------------------------------------------------------------------------- #
MANIFEST_V2 = {
    "manifest_version": 2,
    "experiment_id": "D3_H16_SHADOW_V2",
    "seat": "D3-CODEX-DESIGN-DATA",
    "status": "HOLD_SHADOW_NO_PROMOTION",
    "research_only": True,
    "freeze": {"id": "FREEZE-14", "through_utc_date": "2026-07-23",
               "scope": "shadow_and_infrastructure_only",
               "live_parameter_changes": False, "real_orders": False,
               "pipeline_wiring": False},
    "assets": {"BTC": {"product": "BTC-USD", "sigma_1h": 0.0029},
               "ETH": {"product": "ETH-USD", "sigma_1h": 0.0035},
               "SOL": {"product": "SOL-USD", "sigma_1h": 0.0039},
               "XRP": {"product": "XRP-USD", "sigma_1h": 0.0052}},
    "families": {
        "15m": {"series": ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M"],
                "window_ms": 900_000,
                "primary_arm": {"arm_id": "15m_L860", "L_mills": 860},
                "comparator_arm": {"arm_id": "15m_L840", "L_mills": 840}},
        "hourly": {"series": ["KXBTCD", "KXETHD", "KXSOLD", "KXXRPD"],
                   "window_ms": 3_600_000,
                   "primary_arm": {"arm_id": "hourly_L840", "L_mills": 840},
                   "sensitivity_arm": {"arm_id": "hourly_L860", "L_mills": 860}}},
    "ledger_scope": "asset_x_family_x_arm",
    "pooling_across_assets_or_families": False,
    "price": {"field": "price_mills", "mills_per_dollar": 1000,
              "conversion": "floor(db_real*1000+0.5)", "residual_tolerance": 1e-6},
    "band": {"held_favorite_mid_mills": {"min_inclusive": 840, "max_inclusive": 940},
             "scan_interval": "[close_ms-window_ms,close_ms)",
             "dwell_ms": 3000, "max_interquote_gap_ms": 2000, "min_observed_rows": 3,
             "band_enter_ts": "first_in_band_quote",
             "T0": "first_ts_at_which_complete_dwell_confirmed",
             "incomplete_dwell": "REJECT_BAND_GAP"},
    "z": {"floor_inclusive": 0.8,
          "formula": "side_sign*((spot-reference)/reference)/(sigma_1h*sqrt(max(tau_h,1/3600)))",
          "side_sign": {"yes": 1, "no": -1},
          "spot_source": "latest_fully_closed_coinbase_5m_close_at_or_before_T0",
          "max_spot_age_ms": 360_000,
          "reference": {"15m": "latest_fully_closed_coinbase_5m_close_at_or_before_window_start",
                        "hourly": "strike_from_kalshi_public_market_or_ticker"},
          "missing_or_stale_policy": "REJECT_Z_UNOBSERVABLE"},
    "candles": {"acquisition": "separate_phase_before_replay",
                "network": "coinbase_public_candles_get_only",
                "granularities_s": [300, 60],
                "synchronous_rest_inside_window_decision": False,
                "gap_policy": "fail_closed"},
    "latency": {"s1_primary_ms": 3000, "sensitivity_ms": [0, 10000],
                "arrival_ts": "T0+s1_primary_ms",
                "sensitivity_can_select_arm_or_gate": False},
    "quote_path": {"held_bid_yes": "yes_bid_mills", "held_ask_yes": "yes_ask_mills",
                   "held_bid_no": "1000-yes_ask_mills", "held_ask_no": "1000-yes_bid_mills",
                   "touch": "held_bid_mills<=L_mills",
                   "through": "held_bid_mills<=L_mills-10",
                   "fill_and_through_quote_cutoff": "ts<=close_ms",
                   "post_close_quotes_may_affect_fill_or_through": False,
                   "quote_through_is_fill": False, "current_fill_class": "QUOTE_PROXY_ONLY"},
    "crossed": {"primary_field": "book_crossed",
                "t_star": "first_post_arrival_through_ts",
                "definition": "any_complete_quote_in_[t*-2000,t*+2000]_has_held_ask<=L",
                "book_crossed_window_ms": 2000, "through_mills_offset": 10,
                "unobservable_value": "UNOBSERVABLE",
                "zero_case": {"min_through": 100, "required_crossed_n": 0,
                              "status": "WAIVED_WITH_MONITORING",
                              "upper": "1-0.05^(1/n_through)", "revoked_on_first_crossed": True},
                "nonzero_test": {"min_crossed_n": 20, "test": "one_sided_fisher_exact",
                                 "alpha": 0.05, "crossed_n_1_to_19": "HOLD"},
                "reference_crossed": {"role": "monitor_only", "missing_value": "UNKNOWN"}},
    "unresolved_windows": {"fill_value": "UNOBSERVABLE_GAP",
                           "fraction": "unresolved_eligible_n/official_nonvoid_eligible_n",
                           "scope": "asset_x_family", "remain_in_eligible_denominator": True,
                           "always_report": True, "may_remove_or_reclassify_window": False},
    "settlement": {"method": "KalshiPublic.market(ticker)",
                   "endpoint_class": "kalshi_public_market_get", "authentication": False,
                   "max_requests_per_second": 1, "normal_batch_cap": 100, "smoke_batch_cap": 8,
                   "accept_only": "status in {'finalized','settled'} AND (not is_provisional) AND result in {'yes','no'}",
                   "revision_policy": "append_revision_and_recompute_outcome",
                   "terminal_quote_role": "cross_check_only", "gate_partition": "official_nonvoid_only"},
    "outcome": {"primary_holding": "hold_to_official_settlement", "primary_exits": False,
                "pnl_formula": "official_payout-cost-official_series_fee",
                "primary_metric": "intent_to_treat_net_pnl_per_eligible_window",
                "unfilled_window_pnl": 0, "itt_ev_population": "resolved_eligible_windows_only",
                "fee_usd_maker": 0.0, "proxy_and_official_may_pool": False},
    "regime": {"rv_1h": "sqrt(sum(last_60_complete_1m_log_returns_squared))",
               "role": "report_stratification_only",
               "may_affect_eligibility_arm_gate_or_kill": False},
    "gate_lines": ["G0_EVIDENCE(quote_proxy_can_pass=false,by_design)",
                   "G1_SAMPLE(elig_n>=80 & touch_n>=20 & unresolved<=0.05)",
                   "G2_ARM_DELTA(itt_primary-comparator/sensitivity>=+0.01usd)",
                   "G3_SAFE_WIN(win|book_safe>=0.92)",
                   "G4_CROSSED(fisher_or_zero_case_waiver)",
                   "G5_WILSON_EV(wilson95_lower_net_ev_per_fill>0)"],
    "gate_logic": "all_lines_pass_or_explicit_G4_waiver_per_asset_x_family; no pooled_go",
    "deliverables": ["src/tickstore.py", "src/h16shadow.py",
                     "scripts/h16_shadow_replay.py", "scripts/tickstore_smoke.py",
                     "data/h16_shadow.db"],
}

# ---- derived frozen constants (readability; MANIFEST is the authority) ------ #
_B = MANIFEST_V2["band"]
BAND_LO = _B["held_favorite_mid_mills"]["min_inclusive"]           # 840
BAND_HI = _B["held_favorite_mid_mills"]["max_inclusive"]           # 940
DWELL_MS = _B["dwell_ms"]                                          # 3000
MAX_IQ_GAP_MS = _B["max_interquote_gap_ms"]                        # 2000
MIN_ROWS = _B["min_observed_rows"]                                 # 3
Z_FLOOR = MANIFEST_V2["z"]["floor_inclusive"]                      # 0.8
MAX_SPOT_AGE_MS = MANIFEST_V2["z"]["max_spot_age_ms"]              # 360000
FROZEN_LATENCY_MS = MANIFEST_V2["latency"]["s1_primary_ms"]        # 3000
THROUGH_OFFSET = MANIFEST_V2["crossed"]["through_mills_offset"]    # 10
CROSSED_WIN_MS = MANIFEST_V2["crossed"]["book_crossed_window_ms"]  # 2000
FEE_MAKER = MANIFEST_V2["outcome"]["fee_usd_maker"]                # 0.0
MAX_ARRIVAL_AGE_MS = 5_000       # arrival marketability only fires on a FRESH book
PRODUCT = {a: v["product"] for a, v in MANIFEST_V2["assets"].items()}
SIGMA = {a: v["sigma_1h"] for a, v in MANIFEST_V2["assets"].items()}


def _canon_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


CONFIG_SHA = hashlib.sha256(_canon_json(MANIFEST_V2).encode()).hexdigest()

SCHEMA = """
CREATE TABLE IF NOT EXISTS manifests(
  config_sha256 TEXT PRIMARY KEY, experiment_id TEXT, created_ts TEXT,
  git_commit TEXT, config_json TEXT, data_schema TEXT,
  freeze_id TEXT, research_only INTEGER);
CREATE TABLE IF NOT EXISTS candles(
  product TEXT, granularity_s INTEGER, open_ts INTEGER,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  fetched_ts TEXT, source TEXT, raw_sha256 TEXT,
  PRIMARY KEY (product, granularity_s, open_ts));
CREATE TABLE IF NOT EXISTS intents(
  intent_id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_key TEXT UNIQUE,
  ticker TEXT, series TEXT, family TEXT, asset TEXT, side TEXT,
  band_enter_ms INTEGER, t0_ms INTEGER, arrival_ms INTEGER,
  close_ms INTEGER, close_src TEXT,
  fav_mid_mills INTEGER,
  strike REAL, reference REAL, reference_src TEXT,
  spot REAL, spot_src TEXT, spot_ts_ms INTEGER, candle_age_ms INTEGER,
  sigma_1h REAL, tau_h REAL, z REAL,
  rv_1h REAL, rv_src TEXT, regime TEXT, regime_src TEXT,
  venue TEXT NOT NULL DEFAULT 'production',
  execution_mode TEXT NOT NULL DEFAULT 'quote_proxy',
  coverage_rows INTEGER, coverage_max_gap_ms INTEGER,
  status TEXT, reject_reason TEXT,
  data_quality TEXT, created_ts TEXT);
CREATE TABLE IF NOT EXISTS touches(
  intent_id INTEGER, arm_mills INTEGER,
  fill_class TEXT, touch_ms INTEGER, through_ms INTEGER,
  book_crossed TEXT, reference_crossed TEXT,
  min_held_bid_mills INTEGER, held_ask_at_tstar_mills INTEGER,
  PRIMARY KEY (intent_id, arm_mills));
CREATE TABLE IF NOT EXISTS queue_observations(
  intent_id INTEGER, ts_ms INTEGER, queue_ahead_fp REAL, trade_fp REAL,
  fill_lb_fp REAL, fill_ub_fp REAL, status TEXT, quality_flags TEXT);
CREATE TABLE IF NOT EXISTS settlements(
  event_key TEXT UNIQUE, ticker TEXT, result TEXT,
  official_source TEXT, market_status TEXT, close_time_rest TEXT,
  settled_ts TEXT, observed_ts TEXT, revision INTEGER, raw_sha256 TEXT,
  inferred_result TEXT, infer_agree INTEGER);
CREATE TABLE IF NOT EXISTS settlement_revisions(
  event_key TEXT, revision INTEGER, result TEXT, observed_ts TEXT,
  raw_sha256 TEXT, PRIMARY KEY (event_key, revision));
CREATE TABLE IF NOT EXISTS outcomes(
  intent_id INTEGER, arm_mills INTEGER,
  win INTEGER, fill_class TEXT, fill_px_mills INTEGER,
  fee_usd REAL, gross_pnl_usd REAL, net_pnl_usd REAL, itt_pnl_usd REAL,
  resolved INTEGER, reconciled INTEGER,
  PRIMARY KEY (intent_id, arm_mills));
CREATE TABLE IF NOT EXISTS runs(
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, ran_at TEXT, mode TEXT,
  days_scanned TEXT, config_sha256 TEXT, notes TEXT);
"""


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    now = dt.datetime.now(_UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _now_ms() -> int:
    return int((dt.datetime.now(_UTC) - _EPOCH).total_seconds() * 1000)


def _git_commit() -> str | None:
    import subprocess
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                           text=True, timeout=10)
        return r.stdout.strip() or None
    except Exception:
        return None


def load_manifest() -> tuple[dict, str]:
    """(frozen MANIFEST_V2, its sha256 over canonical json)."""
    return MANIFEST_V2, CONFIG_SHA


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute(
        "INSERT OR IGNORE INTO manifests(config_sha256,experiment_id,created_ts,"
        "git_commit,config_json,data_schema,freeze_id,research_only) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (CONFIG_SHA, MANIFEST_V2["experiment_id"], _now_iso(), _git_commit(),
         _canon_json(MANIFEST_V2), "tickstore_v1", "FREEZE-14", 1))
    c.commit()
    return c


def log_run(mode: str, days: list[str] | None = None, notes: str = "") -> None:
    c = _conn()
    c.execute("INSERT INTO runs(ran_at,mode,days_scanned,config_sha256,notes) "
              "VALUES(?,?,?,?,?)",
              (_now_iso(), mode, ",".join(days or []), CONFIG_SHA, notes))
    c.commit()
    c.close()


def last_backfilled_day() -> str | None:
    """Newest UTC day already covered by a backfill run (for --since-last)."""
    c = _conn()
    rows = c.execute("SELECT days_scanned FROM runs WHERE mode='backfill' "
                     "AND days_scanned <> ''").fetchall()
    c.close()
    days: list[str] = []
    for r in rows:
        days += [d for d in (r["days_scanned"] or "").split(",") if d]
    return max(days) if days else None


# --------------------------------------------------------------------------- #
# §3.2 side/price conversion — the ONE holding-side换算 point (no stray 1000-x)
# --------------------------------------------------------------------------- #
def holding_quote(book, side: str) -> tuple[int | None, int | None]:
    """(held_bid_mills, held_ask_mills). YES=(yes_bid,yes_ask);
    NO=(1000-yes_ask, 1000-yes_bid). Missing leg stays None."""
    yb, ya = book.yes_bid_mills, book.yes_ask_mills
    if side == "yes":
        return yb, ya
    if side == "no":
        return (1000 - ya if ya is not None else None,
                1000 - yb if yb is not None else None)
    raise ValueError(f"side must be 'yes'|'no', got {side!r}")


# --------------------------------------------------------------------------- #
# ticker time parsing (ET -> UTC; cross-midnight is the norm — §3.2)
# --------------------------------------------------------------------------- #
def series_of(ticker: str) -> str:
    return ticker.split("-", 1)[0]


def asset_of(series: str) -> str | None:
    for a in MANIFEST_V2["assets"]:
        if a in series:
            return a
    return None


def family_of(series: str) -> str | None:
    for fam, spec in MANIFEST_V2["families"].items():
        if series in spec["series"]:
            return fam
    return None


def _dt_to_ms(d: dt.datetime) -> int:
    return int((d.astimezone(_UTC) - _EPOCH).total_seconds() * 1000)


def parse_close_ms(ticker: str, family: str) -> tuple[int, str]:
    """15m 'KXBTC15M-26JUL072000-00' HHMM=close; hourly 'KXBTCD-26JUL0720-T..' HH=close.
    seg is ET wall time -> UTC (20:00 ET == 00:00 UTC next day)."""
    seg = ticker.split("-")[1]
    yy, mon, dd = int(seg[0:2]), _MONTHS[seg[2:5]], int(seg[5:7])
    if family == "15m":
        hh, mm = int(seg[7:9]), int(seg[9:11])
    else:
        hh, mm = int(seg[7:9]), 0
    d = dt.datetime(2000 + yy, mon, dd, hh, mm, tzinfo=ET)
    return _dt_to_ms(d), "ticker_et"


# --------------------------------------------------------------------------- #
# §3.5 candle acquisition (Coinbase public GET; judgment path never fetches)
# --------------------------------------------------------------------------- #
def _http_get_json(url: str, timeout: int = 20, tries: int = 4):
    req = urllib.request.Request(
        url, headers={"User-Agent": "h16shadow-research/2 (FREEZE-14 read-only)"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:
                time.sleep(1.5 * (i + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if i < tries - 1:
                time.sleep(1.0 * (i + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def fetch_candles(products: list[str], granularity_s: int,
                  start_ms: int, end_ms: int) -> int:
    """Acquisition phase: paginate Coinbase public candles (<=300/req, ~1 rps),
    idempotent upsert into candles. Never called on the judgment path (manifest
    synchronous_rest_inside_window_decision=false)."""
    c = _conn()
    step = granularity_s * 300 * 1000
    n = 0
    for product in products:
        cur = start_ms
        while cur < end_ms:
            chunk_end = min(end_ms, cur + step)
            url = (f"https://api.exchange.coinbase.com/products/{product}/candles"
                   f"?granularity={granularity_s}"
                   f"&start={ms_to_iso(cur)}&end={ms_to_iso(chunk_end)}")
            try:
                data = _http_get_json(url)
            except Exception as e:
                print(f"WARN candles {product} {granularity_s}s: {e}")
                cur = chunk_end
                time.sleep(1.0)
                continue
            for row in data or []:
                if not row or len(row) < 6:
                    continue
                try:
                    open_ts = int(row[0])
                    low, high, op, cl, vol = (float(row[1]), float(row[2]),
                                              float(row[3]), float(row[4]), float(row[5]))
                except (TypeError, ValueError):
                    continue
                sha = hashlib.sha256(
                    _canon_json(row).encode()).hexdigest()
                c.execute(
                    "INSERT INTO candles(product,granularity_s,open_ts,open,high,low,"
                    "close,volume,fetched_ts,source,raw_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(product,granularity_s,open_ts) DO UPDATE SET "
                    "open=excluded.open,high=excluded.high,low=excluded.low,"
                    "close=excluded.close,volume=excluded.volume,"
                    "fetched_ts=excluded.fetched_ts,raw_sha256=excluded.raw_sha256",
                    (product, granularity_s, open_ts, op, high, low, cl, vol,
                     _now_iso(), "coinbase_exchange", sha))
                n += 1
            c.commit()
            cur = chunk_end
            time.sleep(1.0)          # ~1 rps public limit
    c.close()
    return n


def _candle_close_at_or_before(c, product: str, gran: int, ts_ms: int):
    """Latest FULLY-CLOSED gran-candle whose close (open_ts+gran) <= ts.
    -> (close_price, close_ms, age_ms) or None. Reads local cache only."""
    t_sec = ts_ms // 1000
    row = c.execute(
        "SELECT open_ts, close FROM candles WHERE product=? AND granularity_s=? "
        "AND open_ts + ? <= ? ORDER BY open_ts DESC LIMIT 1",
        (product, gran, gran, t_sec)).fetchone()
    if row is None:
        return None
    close_ms = (row["open_ts"] + gran) * 1000
    return float(row["close"]), close_ms, ts_ms - close_ms


def _rv_1h(c, product: str, t0_ms: int) -> tuple[float | None, str]:
    """sqrt(sum of last 60 complete 1m log-returns squared) before T0."""
    t_sec = t0_ms // 1000
    rows = c.execute(
        "SELECT open_ts, close FROM candles WHERE product=? AND granularity_s=60 "
        "AND open_ts + 60 <= ? ORDER BY open_ts DESC LIMIT 61",
        (product, t_sec)).fetchall()
    if len(rows) < 61:
        return None, "UNKNOWN"
    closes = [float(r["close"]) for r in rows[::-1]]
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0]
    if len(rets) < 60:
        return None, "UNKNOWN"
    return math.sqrt(sum(x * x for x in rets[-60:])), "coinbase_1m"


def _regime(rv: float | None, asset: str) -> tuple[str, str]:
    if rv is None:
        return "UNKNOWN", "UNKNOWN"
    ratio = rv / SIGMA[asset] if SIGMA[asset] else 0.0
    lab = "HIGH" if ratio > 1.5 else "LOW" if ratio < 0.67 else "MID"
    return lab, "rv_vs_sigma1h"


# --------------------------------------------------------------------------- #
# §3.1 band + 3s dwell -> T0
# --------------------------------------------------------------------------- #
def _band_side(yb, ya):
    """(in_band, side, fav_mid_mills). Needs both legs (mid); the favorite is the
    side whose mid sits in [840,940] (yes_mid + no_mid == 1000, only one can)."""
    if yb is None or ya is None:
        return False, None, None
    yes_mid = (yb + ya) / 2.0
    if BAND_LO <= yes_mid <= BAND_HI:
        return True, "yes", yes_mid
    no_mid = 1000 - yes_mid
    if BAND_LO <= no_mid <= BAND_HI:
        return True, "no", no_mid
    return False, None, None


def _scan_band_t0(store: TickStore, ticker: str, family: str, close_ms: int,
                  window_ms: int) -> dict | None:
    """Forward scan [close-window, close): first-in-band marker + a clean 3000ms /
    >=3-row / gap<=2000ms dwell on one favorite side. Never in band -> None (not an
    H16 window). In band but no clean dwell -> REJECT_BAND_GAP (recorded, not dropped).
    Coverage (rows + edge-inclusive max gap) is derived from the single pass."""
    start, end = close_ms - window_ms, close_ms - 1
    first_band = None
    run_start = run_side = prev_ts = None
    run_rows = 0
    cov_rows = 0
    cov_prev = cov_first = cov_last = None
    cov_max_gap = 0
    hit = None
    for b in store.iter_books(ticker, start, end):
        cov_rows += 1
        if cov_first is None:
            cov_first = b.ts_ms
        if cov_prev is not None:
            cov_max_gap = max(cov_max_gap, b.ts_ms - cov_prev)
        cov_prev = cov_last = b.ts_ms
        if hit is not None:
            continue                          # dwell already confirmed; finish coverage only
        in_band, side, fav = _band_side(b.yes_bid_mills, b.yes_ask_mills)
        if in_band and first_band is None:
            first_band = (b.ts_ms, side, fav)
        if not in_band:
            run_start = run_side = prev_ts = None
            run_rows = 0
            continue
        if run_start is None or side != run_side or (b.ts_ms - prev_ts) > MAX_IQ_GAP_MS:
            run_start, run_side, prev_ts, run_rows = b.ts_ms, side, b.ts_ms, 1
        else:
            prev_ts, run_rows = b.ts_ms, run_rows + 1
        if run_rows >= MIN_ROWS and (b.ts_ms - run_start) >= DWELL_MS:
            hit = {"side": run_side, "t0_ms": b.ts_ms, "fav_mid_mills": int(round(fav))}
    if cov_first is not None:
        cov_max_gap = max(cov_max_gap, cov_first - start, end - cov_last)
    else:
        cov_max_gap = max(0, end - start)
    if hit is not None:
        return {"side": hit["side"], "band_enter_ms": first_band[0],
                "t0_ms": hit["t0_ms"], "fav_mid_mills": hit["fav_mid_mills"],
                "coverage_rows": cov_rows, "coverage_max_gap_ms": cov_max_gap,
                "reject": None}
    if first_band is None:
        return None
    return {"side": first_band[1], "band_enter_ms": first_band[0], "t0_ms": None,
            "fav_mid_mills": int(round(first_band[2])), "coverage_rows": cov_rows,
            "coverage_max_gap_ms": cov_max_gap, "reject": "REJECT_BAND_GAP"}


# --------------------------------------------------------------------------- #
# §3.1 z (reads candle cache only; fail-closed on missing/stale — §3.5)
# --------------------------------------------------------------------------- #
def _compute_z(c, asset: str, side: str, ticker: str, family: str,
               t0_ms: int, close_ms: int, window_ms: int) -> dict:
    product = PRODUCT[asset]
    spot_info = _candle_close_at_or_before(c, product, 300, t0_ms)
    if spot_info is None or spot_info[2] > MAX_SPOT_AGE_MS:
        return {"reject": "REJECT_Z_UNOBSERVABLE"}
    spot, spot_close_ms, spot_age = spot_info
    if family == "15m":
        ref_info = _candle_close_at_or_before(c, product, 300, close_ms - window_ms)
        if ref_info is None:
            return {"reject": "REJECT_Z_UNOBSERVABLE"}
        reference, reference_src, strike = ref_info[0], "coinbase_5m_window_start", None
    else:
        strike = strike_of(ticker)
        if strike is None:
            return {"reject": "REJECT_Z_UNOBSERVABLE"}
        reference, reference_src = strike, "ticker_strike"
    if reference == 0:
        return {"reject": "REJECT_Z_UNOBSERVABLE"}
    tau_h = (close_ms - t0_ms) / 3_600_000.0
    side_sign = 1.0 if side == "yes" else -1.0
    z = side_sign * ((spot - reference) / reference) / \
        (SIGMA[asset] * math.sqrt(max(tau_h, 1.0 / 3600.0)))
    return {"reject": None, "spot": spot, "spot_src": "coinbase_5m",
            "spot_ts_ms": spot_close_ms, "candle_age_ms": spot_age,
            "reference": reference, "reference_src": reference_src,
            "strike": strike, "sigma_1h": SIGMA[asset], "tau_h": tau_h, "z": z}


def _compute_intent_fields(store: TickStore, c, ticker: str, family: str,
                           close_ms: int, close_src: str) -> dict | None:
    """Full intent record (or None if not a band window). Shared by detect_windows
    and the settle-time REST-close recompute."""
    series = series_of(ticker)
    asset = asset_of(series)
    window_ms = MANIFEST_V2["families"][family]["window_ms"]
    scan = _scan_band_t0(store, ticker, family, close_ms, window_ms)
    if scan is None:
        return None
    side = scan["side"]
    t0_ms = scan["t0_ms"]
    reject = scan["reject"]
    arrival_ms = (t0_ms + FROZEN_LATENCY_MS) if t0_ms is not None else None
    z = {}
    if reject is None:
        z = _compute_z(c, asset, side, ticker, family, t0_ms, close_ms, window_ms)
        reject = z.get("reject")
    rv, rv_src = (_rv_1h(c, PRODUCT[asset], t0_ms) if t0_ms is not None
                  else (None, "UNKNOWN"))
    regime, regime_src = _regime(rv, asset)
    return {
        "event_key": f"{ticker}|{side}|{CONFIG_SHA[:12]}",
        "ticker": ticker, "series": series, "family": family, "asset": asset,
        "side": side, "band_enter_ms": scan["band_enter_ms"], "t0_ms": t0_ms,
        "arrival_ms": arrival_ms, "close_ms": close_ms, "close_src": close_src,
        "fav_mid_mills": scan["fav_mid_mills"],
        "strike": z.get("strike"), "reference": z.get("reference"),
        "reference_src": z.get("reference_src"),
        "spot": z.get("spot"), "spot_src": z.get("spot_src"),
        "spot_ts_ms": z.get("spot_ts_ms"), "candle_age_ms": z.get("candle_age_ms"),
        "sigma_1h": z.get("sigma_1h"), "tau_h": z.get("tau_h"), "z": z.get("z"),
        "rv_1h": rv, "rv_src": rv_src, "regime": regime, "regime_src": regime_src,
        "coverage_rows": scan["coverage_rows"],
        "coverage_max_gap_ms": scan["coverage_max_gap_ms"],
        "status": "REJECTED" if reject else "ACTIVE", "reject_reason": reject,
    }


_INTENT_COLS = ("event_key", "ticker", "series", "family", "asset", "side",
                "band_enter_ms", "t0_ms", "arrival_ms", "close_ms", "close_src",
                "fav_mid_mills", "strike", "reference", "reference_src", "spot",
                "spot_src", "spot_ts_ms", "candle_age_ms", "sigma_1h", "tau_h", "z",
                "rv_1h", "rv_src", "regime", "regime_src", "coverage_rows",
                "coverage_max_gap_ms", "status", "reject_reason")


def detect_windows(store: TickStore, day: str, family: str) -> int:
    """Scan a partition's family series: band+dwell -> intent upsert (event_key
    UNIQUE dedups cross-midnight re-processing). Returns new-intent count."""
    fam = MANIFEST_V2["families"][family]
    c = _conn()
    made = 0
    for series in fam["series"]:
        for ticker in store.tickers(day, like=f"{series}-*"):
            try:
                close_ms, close_src = parse_close_ms(ticker, family)
            except (KeyError, ValueError, IndexError):
                continue
            if c.execute("SELECT 1 FROM intents WHERE ticker=? LIMIT 1",
                         (ticker,)).fetchone():
                continue                      # already have this ticker's intent (cross-midnight dedup)
            fields = _compute_intent_fields(store, c, ticker, family, close_ms, close_src)
            if fields is None:
                continue
            vals = [fields[k] for k in _INTENT_COLS]
            before = c.total_changes
            c.execute(
                f"INSERT OR IGNORE INTO intents({','.join(_INTENT_COLS)},venue,"
                f"execution_mode,data_quality,created_ts) VALUES("
                f"{','.join('?' for _ in _INTENT_COLS)},?,?,?,?)",
                (*vals, VENUE, EXECUTION_MODE, None, _now_iso()))
            if c.total_changes > before:      # per-statement delta (total_changes is cumulative)
                made += 1
    c.commit()
    c.close()
    return made


# --------------------------------------------------------------------------- #
# §3.3 fill classification / evaluate
# --------------------------------------------------------------------------- #
def _arms_of(family: str) -> list[tuple[str, int]]:
    fam = MANIFEST_V2["families"][family]
    key2 = "comparator_arm" if family == "15m" else "sensitivity_arm"
    return [(fam["primary_arm"]["arm_id"], fam["primary_arm"]["L_mills"]),
            (fam[key2]["arm_id"], fam[key2]["L_mills"])]


def _gap_ok(start_ms: int, end_ms: int, points: list[int], max_gap: int) -> bool:
    if not points:
        return False
    if points[0] - start_ms > max_gap:
        return False
    for a, b in zip(points, points[1:]):
        if b - a > max_gap:
            return False
    return (end_ms - points[-1]) <= max_gap


def _book_crossed(store, ticker, side, tstar, close_ms, L) -> str:
    """§3.3: complete quote in [t*-2s, t*+2s] (ts<=close_ms) with held ask<=L -> '1';
    fully covered & none crossed -> '0'; coverage incomplete / right edge truncated
    by close / gap>2s -> 'UNOBSERVABLE' (never 0)."""
    lo, hi_want = tstar - CROSSED_WIN_MS, tstar + CROSSED_WIN_MS
    hi = min(hi_want, close_ms)
    if hi < hi_want:
        return "UNOBSERVABLE"               # right edge is post-close (ghost) -> unobservable
    complete = []
    for b in store.iter_books(ticker, lo, hi):
        hb, ha = holding_quote(b, side)
        if hb is not None and ha is not None:
            complete.append((b.ts_ms, ha))
    if not complete:
        return "UNOBSERVABLE"
    ts = [t for t, _ in complete]
    if not _gap_ok(lo, hi, ts, MAX_IQ_GAP_MS):
        return "UNOBSERVABLE"
    return "1" if any(ha <= L for _, ha in complete) else "0"


def _reference_crossed(c, asset, side, tstar, reference) -> str:
    if reference is None:
        return "UNKNOWN"
    info = _candle_close_at_or_before(c, PRODUCT[asset], 300, tstar)
    if info is None:
        return "UNKNOWN"
    spot = info[0]
    wrong = (spot < reference) if side == "yes" else (spot > reference)
    return "1" if wrong else "0"


def _classify_arm(store, c, ticker, side, asset, reference, arrival_ms, close_ms,
                  L, books) -> dict:
    # arrival marketability (FRESH book only): held ask<=L -> not a maker
    arr = store.book_at(ticker, arrival_ms, max_age_ms=MAX_ARRIVAL_AGE_MS)
    if arr is not None:
        _, arr_ask = holding_quote(arr, side)
        if arr_ask is not None and arr_ask <= L:
            return {"fill_class": "REJECT_MARKETABLE", "touch_ms": None,
                    "through_ms": None, "book_crossed": None,
                    "reference_crossed": None, "min_held_bid": None,
                    "held_ask_at_tstar": arr_ask}
    touch_ms = through_ms = None
    min_held_bid = None
    bid_points = []
    if arr is not None:
        arr_bid, _ = holding_quote(arr, side)
        if arr_bid is not None:
            bid_points.append(arr.ts_ms)
    for b in books:
        if b.ts_ms < arrival_ms or b.ts_ms > close_ms:
            continue                          # ts<=close_ms hard limit (ghost rows out)
        hb, _ = holding_quote(b, side)
        if hb is None:
            continue
        bid_points.append(b.ts_ms)
        if min_held_bid is None or hb < min_held_bid:
            min_held_bid = hb
        if touch_ms is None and hb <= L:
            touch_ms = b.ts_ms
        if through_ms is None and hb <= L - THROUGH_OFFSET:
            through_ms = b.ts_ms
    bid_points.sort()
    if through_ms is not None:
        fill_class = "THROUGH_1C"
    elif not _gap_ok(arrival_ms, close_ms, bid_points, MAX_IQ_GAP_MS):
        fill_class = "UNOBSERVABLE_GAP"       # a through could hide in an unseen gap
    elif touch_ms is not None:
        fill_class = "TOUCH_UB"
    else:
        fill_class = "NO_TOUCH"
    book_crossed = ref_crossed = held_ask_tstar = None
    if fill_class == "THROUGH_1C":
        book_crossed = _book_crossed(store, ticker, side, through_ms, close_ms, L)
        ref_crossed = _reference_crossed(c, asset, side, through_ms, reference)
        near = store.book_at(ticker, through_ms, max_age_ms=MAX_IQ_GAP_MS)
        if near is not None:
            _, held_ask_tstar = holding_quote(near, side)
    return {"fill_class": fill_class, "touch_ms": touch_ms, "through_ms": through_ms,
            "book_crossed": book_crossed, "reference_crossed": ref_crossed,
            "min_held_bid": min_held_bid, "held_ask_at_tstar": held_ask_tstar}


def evaluate_intent(store: TickStore, intent) -> None:
    """[arrival, close_ms] replay for each arm -> touches. ts<=close_ms hard limit.
    Only ACTIVE + z-eligible (z>=0.8) intents are evaluated."""
    if intent["status"] != "ACTIVE" or intent["arrival_ms"] is None:
        return
    if intent["z"] is None or intent["z"] < Z_FLOOR:
        return
    family, side, ticker = intent["family"], intent["side"], intent["ticker"]
    close_ms, arrival_ms = intent["close_ms"], intent["arrival_ms"]
    asset, reference = intent["asset"], intent["reference"]
    c = _conn()
    books = list(store.iter_books(ticker, arrival_ms, close_ms))
    for _arm_id, L in _arms_of(family):
        r = _classify_arm(store, c, ticker, side, asset, reference,
                          arrival_ms, close_ms, L, books)
        c.execute(
            "INSERT OR REPLACE INTO touches(intent_id,arm_mills,fill_class,touch_ms,"
            "through_ms,book_crossed,reference_crossed,min_held_bid_mills,"
            "held_ask_at_tstar_mills) VALUES(?,?,?,?,?,?,?,?,?)",
            (intent["intent_id"], L, r["fill_class"], r["touch_ms"], r["through_ms"],
             r["book_crossed"], r["reference_crossed"], r["min_held_bid"],
             r["held_ask_at_tstar"]))
    c.commit()
    c.close()


def evaluate_all(store: TickStore) -> int:
    c = _conn()
    ids = [r["intent_id"] for r in c.execute(
        "SELECT intent_id FROM intents WHERE status='ACTIVE' AND arrival_ms IS NOT NULL "
        "AND z IS NOT NULL AND z >= ? AND intent_id NOT IN "
        "(SELECT DISTINCT intent_id FROM touches)", (Z_FLOOR,))]
    c.close()
    n = 0
    for iid in ids:
        c = _conn()
        intent = c.execute("SELECT * FROM intents WHERE intent_id=?", (iid,)).fetchone()
        c.close()
        if intent is not None:
            evaluate_intent(store, intent)
            n += 1
    return n


# --------------------------------------------------------------------------- #
# §3.5 settlements (official only; terminal quote is cross-check)
# --------------------------------------------------------------------------- #
def _rest_close_ms(close_time: str | None) -> int | None:
    if not close_time:
        return None
    try:
        return iso_to_ms(close_time if close_time.endswith("Z")
                         else close_time.replace("+00:00", "") + "Z")
    except Exception:
        try:
            d = dt.datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            return _dt_to_ms(d)
        except Exception:
            return None


def _infer_terminal(store: TickStore, ticker: str, close_ms: int) -> str | None:
    """Cross-check only: last non-empty book in (close_ms, close_ms+600s] priced
    near 1 -> yes, near 0 -> no. Never a substitute for official result."""
    last_mid = None
    for b in store.iter_books(ticker, close_ms + 1, close_ms + 600_000):
        yb, ya = b.yes_bid_mills, b.yes_ask_mills
        if yb is not None and ya is not None:
            last_mid = (yb + ya) / 2.0
        elif ya is not None:
            last_mid = ya
        elif yb is not None:
            last_mid = yb
    if last_mid is None:
        return None
    return "yes" if last_mid >= 500 else "no"


def _recompute_event(store: TickStore, c, event_key: str, close_ms_rest: int) -> None:
    """CLOSE_MISMATCH -> 以 REST 为准重算 (§3.2)."""
    row = c.execute("SELECT * FROM intents WHERE event_key=?", (event_key,)).fetchone()
    if row is None:
        return
    fields = _compute_intent_fields(store, c, row["ticker"], row["family"],
                                    close_ms_rest, "rest")
    if fields is None:
        return
    sets = ",".join(f"{k}=?" for k in _INTENT_COLS if k != "event_key")
    vals = [fields[k] for k in _INTENT_COLS if k != "event_key"]
    c.execute(f"UPDATE intents SET {sets}, data_quality=COALESCE(data_quality,'')||'CLOSE_MISMATCH;' "
              f"WHERE event_key=?", (*vals, event_key))
    c.execute("DELETE FROM touches WHERE intent_id=?", (row["intent_id"],))
    c.commit()
    fresh = c.execute("SELECT * FROM intents WHERE event_key=?", (event_key,)).fetchone()
    if fresh is not None:
        evaluate_intent(store, fresh)


def fetch_settlements(pub: KalshiPublic, limit: int = 100, rps: float = 1.0) -> int:
    """Official settlement only: status in {'finalized','settled'} AND not
    is_provisional AND result in {'yes','no'}. Failure/pending stays pending, never
    faked void. Revisions append. Terminal quote is cross-check. <=1 rps."""
    c = _conn()
    now_ms = _now_ms()
    rows = c.execute(
        "SELECT DISTINCT i.event_key, i.ticker, i.close_ms FROM intents i "
        "LEFT JOIN settlements s ON s.event_key=i.event_key "
        "WHERE i.close_ms < ? AND s.result IS NULL ORDER BY i.close_ms LIMIT ?",
        (now_ms, limit)).fetchall()
    done = 0
    store = None
    for r in rows:
        try:
            mk = pub.market(r["ticker"])
        except Exception as e:
            print(f"WARN settle {r['ticker']}: {e} (pending, not void)")
            time.sleep(1.0 / max(rps, 0.1))
            continue
        status = mk.get("status")
        result = mk.get("result")
        prov = bool(mk.get("is_provisional"))
        close_rest = mk.get("close_time")
        if status in ("finalized", "settled") and (not prov) and result in ("yes", "no"):
            raw = _canon_json({"status": status, "result": result,
                               "is_provisional": prov, "close_time": close_rest})
            sha = hashlib.sha256(raw.encode()).hexdigest()
            prev = c.execute("SELECT result,revision FROM settlements WHERE event_key=?",
                             (r["event_key"],)).fetchone()
            rev = 0
            if prev is not None and prev["result"] != result:
                rev = (prev["revision"] or 0) + 1
            c.execute("INSERT OR REPLACE INTO settlement_revisions(event_key,revision,"
                      "result,observed_ts,raw_sha256) VALUES(?,?,?,?,?)",
                      (r["event_key"], rev, result, _now_iso(), sha))
            if store is None:
                store = TickStore()
            inferred = _infer_terminal(store, r["ticker"], r["close_ms"])
            infer_agree = (1 if inferred == result else 0) if inferred in ("yes", "no") else None
            close_ms_rest = _rest_close_ms(close_rest)
            if close_ms_rest is not None and abs(close_ms_rest - r["close_ms"]) > 1000:
                _recompute_event(store, c, r["event_key"], close_ms_rest)
            c.execute(
                "INSERT OR REPLACE INTO settlements(event_key,ticker,result,"
                "official_source,market_status,close_time_rest,settled_ts,observed_ts,"
                "revision,raw_sha256,inferred_result,infer_agree) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["event_key"], r["ticker"], result, "kalshi_public_market_get",
                 status, close_rest, _now_iso(), _now_iso(), rev, sha,
                 inferred, infer_agree))
            c.commit()
            done += 1
        time.sleep(1.0 / max(rps, 0.1))
    c.close()
    if store is not None:
        store.close()
    return done


# --------------------------------------------------------------------------- #
# §3.5 outcomes (ITT semantics, §3.3 anti-survivorship铁则)
# --------------------------------------------------------------------------- #
def compute_outcomes() -> int:
    c = _conn()
    rows = c.execute(
        "SELECT t.intent_id,t.arm_mills,t.fill_class,i.side,i.event_key "
        "FROM touches t JOIN intents i ON i.intent_id=t.intent_id "
        "WHERE i.status='ACTIVE'").fetchall()
    n = 0
    for r in rows:
        s = c.execute("SELECT result FROM settlements WHERE event_key=?",
                      (r["event_key"],)).fetchone()
        official = s is not None and s["result"] in ("yes", "no")
        result = s["result"] if official else None
        fill_class, L = r["fill_class"], r["arm_mills"]
        resolved = 0 if fill_class == "UNOBSERVABLE_GAP" else 1
        win = fill_px = None
        gross = net = itt = 0.0
        fee = FEE_MAKER
        if official:
            win = 1 if result == r["side"] else 0
            if fill_class == "THROUGH_1C":
                fill_px = L
                payout = 1.0 if win else 0.0
                gross = payout - L / 1000.0
                net = gross - fee
                itt = net
        c.execute(
            "INSERT OR REPLACE INTO outcomes(intent_id,arm_mills,win,fill_class,"
            "fill_px_mills,fee_usd,gross_pnl_usd,net_pnl_usd,itt_pnl_usd,resolved,"
            "reconciled) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (r["intent_id"], L, win, fill_class, fill_px, fee, gross, net, itt,
             resolved, 1 if official else 0))
        n += 1
    c.commit()
    c.close()
    return n


# --------------------------------------------------------------------------- #
# stats (stdlib only)
# --------------------------------------------------------------------------- #
def wilson_lower(k: int, n: int, z: float = 1.959963985) -> float:
    if n == 0:
        return 0.0
    p = k / n
    d = 1.0 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (center - margin) / d


def zero_case_upper(n_through: int) -> float:
    if n_through <= 0:
        return 1.0
    return 1.0 - 0.05 ** (1.0 / n_through)


def fisher_one_sided(a: int, b: int, cc: int, d: int) -> float:
    """Upper-tail Fisher exact P(X>=a) for the 2x2 [[a,b],[cc,d]] (safe vs crossed
    x win vs loss). Hypergeometric tail via math.comb — no third-party lib."""
    n, K, row1 = a + b + cc + d, a + cc, a + b
    if n == 0 or K == 0 or row1 == 0:
        return 1.0
    denom = math.comb(n, row1)
    x_max = min(row1, K)
    p = 0.0
    for x in range(a, x_max + 1):
        p += math.comb(K, x) * math.comb(n - K, row1 - x) / denom
    return p


def block_bootstrap_ci(blocks: dict[str, list[float]], n_boot: int = 2000,
                       alpha: float = 0.05, seed: int = 1234) -> tuple[float | None, float | None]:
    """Resample UTC-day blocks with replacement; CI on the pooled mean."""
    keys = [k for k, v in blocks.items() if v]
    if not keys:
        return None, None
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        ssum = 0.0
        sn = 0
        for _ in range(len(keys)):
            vals = blocks[rng.choice(keys)]
            ssum += sum(vals)
            sn += len(vals)
        means.append(ssum / sn if sn else 0.0)
    means.sort()
    lo = means[int((alpha / 2) * len(means))]
    hi = means[min(len(means) - 1, int((1 - alpha / 2) * len(means)))]
    return lo, hi


# --------------------------------------------------------------------------- #
# §3.5 report — per asset×family×arm gate ledger (no pooled分母)
# --------------------------------------------------------------------------- #
def report(official_only: bool = True) -> str:
    c = _conn()
    intents = {r["intent_id"]: r for r in c.execute("SELECT * FROM intents")}
    settled = {r["event_key"]: r for r in c.execute("SELECT * FROM settlements")}
    touches = {(r["intent_id"], r["arm_mills"]): r
               for r in c.execute("SELECT * FROM touches")}
    outs = {(r["intent_id"], r["arm_mills"]): r
            for r in c.execute("SELECT * FROM outcomes")}
    c.close()

    def eligible(it) -> bool:
        if it["status"] != "ACTIVE" or it["reject_reason"] is not None:
            return False
        if it["z"] is None or it["z"] < Z_FLOOR:
            return False
        if official_only and not (it["event_key"] in settled
                                  and settled[it["event_key"]]["result"] in ("yes", "no")):
            return False
        return True

    lines = [
        f"H16 SHADOW REPORT  config={CONFIG_SHA[:12]}  venue={VENUE} mode={EXECUTION_MODE}",
        "FREEZE-14 research-only. print≠fill: quote-proxy touches are an UPPER BOUND,",
        "never confirmed maker fills — G0 is FAIL by design (quote proxy can't GO).",
        f"partition: {'official-settled only' if official_only else 'all eligible'}",
        "",
    ]

    elig_ids = [iid for iid, it in intents.items() if eligible(it)]
    by_af: dict[tuple[str, str], list[int]] = {}
    for iid in elig_ids:
        it = intents[iid]
        by_af.setdefault((it["asset"], it["family"]), []).append(iid)

    if not elig_ids:
        n_all = sum(1 for it in intents.values()
                    if it["status"] == "ACTIVE" and it["reject_reason"] is None
                    and it["z"] is not None and it["z"] >= Z_FLOOR)
        n_settled = len(settled)
        lines.append(f"no eligible {'official-settled ' if official_only else ''}windows "
                     f"(z>={Z_FLOOR} ACTIVE = {n_all}; official settlements = {n_settled}).")
        lines.append("run: candles -> backfill -> settle, then report.")
        return "\n".join(lines)

    for (asset, family) in sorted(by_af):
        ids = by_af[(asset, family)]
        arms = _arms_of(family)
        primary_L = arms[0][1]
        # unresolved fraction (asset×family) from the primary arm
        unresolved = sum(1 for iid in ids
                         if (iid, primary_L) in outs and outs[(iid, primary_L)]["resolved"] == 0)
        unres_frac = unresolved / len(ids) if ids else 0.0
        lines.append(f"=== {asset} {family}  eligible_windows={len(ids)}  "
                     f"unresolved={unresolved} ({unres_frac*100:.1f}%) ===")

        arm_itt: dict[int, float] = {}
        for arm_id, L in arms:
            touch_n = through_n = safe_n = crossed_n = unobs_n = 0
            win_safe = 0
            itt_vals = []
            blocks: dict[str, list[float]] = {}
            fills = []
            for iid in ids:
                t = touches.get((iid, L))
                o = outs.get((iid, L))
                if t is None or o is None:
                    continue
                fc = t["fill_class"]
                if fc in ("TOUCH_UB", "THROUGH_1C"):
                    touch_n += 1
                if fc == "THROUGH_1C":
                    through_n += 1
                    if t["book_crossed"] == "0":
                        safe_n += 1
                        if o["win"] == 1:
                            win_safe += 1
                    elif t["book_crossed"] == "1":
                        crossed_n += 1
                    else:
                        unobs_n += 1
                    fills.append(o["net_pnl_usd"])
                if o["resolved"] == 1:
                    itt_vals.append(o["itt_pnl_usd"])
                    day = ms_to_iso(intents[iid]["close_ms"])[:10]
                    blocks.setdefault(day, []).append(o["itt_pnl_usd"])
            itt_ev = (sum(itt_vals) / len(itt_vals)) if itt_vals else 0.0
            arm_itt[L] = itt_ev
            ev_fill = (sum(fills) / len(fills)) if fills else 0.0
            win_safe_rate = (win_safe / safe_n) if safe_n else 0.0
            wl = wilson_lower(win_safe, safe_n)
            wl_ev = (wl - L / 1000.0) if safe_n else None    # each arm vs its own L
            ci_lo, ci_hi = block_bootstrap_ci(blocks)
            tag = arm_id + ("*" if L == primary_L else "")
            lines.append(
                f"  arm {tag} L={L}: touch={touch_n} through={through_n} "
                f"safe={safe_n} crossed={crossed_n} crossed_unobs={unobs_n} "
                f"win|safe={win_safe_rate*100:.1f}% "
                f"ITT_EV/win={itt_ev*100:+.2f}c EV/fill={ev_fill*100:+.2f}c "
                f"Wilson95_EV/fill_lo={('%+.2fc' % (wl_ev*100)) if wl_ev is not None else 'n/a'} "
                f"dayCI=[{('%+.2fc'%(ci_lo*100)) if ci_lo is not None else 'na'},"
                f"{('%+.2fc'%(ci_hi*100)) if ci_hi is not None else 'na'}]")

        # ---- gate lines (primary arm; G2 needs both) ----
        pL = arms[0][1]
        cL = arms[1][1]
        p_touch = sum(1 for iid in ids if touches.get((iid, pL))
                      and touches[(iid, pL)]["fill_class"] in ("TOUCH_UB", "THROUGH_1C"))
        p_through = sum(1 for iid in ids if touches.get((iid, pL))
                        and touches[(iid, pL)]["fill_class"] == "THROUGH_1C")
        p_safe = sum(1 for iid in ids if touches.get((iid, pL))
                     and touches[(iid, pL)]["fill_class"] == "THROUGH_1C"
                     and touches[(iid, pL)]["book_crossed"] == "0")
        p_safe_win = sum(1 for iid in ids if touches.get((iid, pL))
                         and touches[(iid, pL)]["fill_class"] == "THROUGH_1C"
                         and touches[(iid, pL)]["book_crossed"] == "0"
                         and outs.get((iid, pL)) and outs[(iid, pL)]["win"] == 1)
        p_crossed = sum(1 for iid in ids if touches.get((iid, pL))
                        and touches[(iid, pL)]["fill_class"] == "THROUGH_1C"
                        and touches[(iid, pL)]["book_crossed"] == "1")
        crossed_all_obs = all(touches[(iid, pL)]["book_crossed"] in ("0", "1")
                              for iid in ids if touches.get((iid, pL))
                              and touches[(iid, pL)]["fill_class"] == "THROUGH_1C")

        g1 = "PASS" if (len(ids) >= 80 and p_touch >= 20 and unres_frac <= 0.05) \
            else f"FAIL(n={len(ids)},touch={p_touch},unres={unres_frac*100:.1f}%)"
        delta = arm_itt.get(pL, 0.0) - arm_itt.get(cL, 0.0)
        g2 = "PASS" if delta >= 0.01 else f"FAIL(Δ={delta*100:+.2f}c)"
        win_safe_rate = (p_safe_win / p_safe) if p_safe else 0.0
        g3 = ("PASS" if p_safe and win_safe_rate >= 0.92
              else f"{'FAIL' if p_safe else 'INSUFFICIENT'}({win_safe_rate*100:.1f}%,safe={p_safe})")
        # G4 crossed
        if p_crossed == 0 and p_through >= 100 and crossed_all_obs:
            g4 = f"WAIVED_WITH_MONITORING(upper={zero_case_upper(p_through)*100:.2f}%)"
        elif p_crossed == 0:
            g4 = f"INSUFFICIENT(through={p_through}<100 or unobserved crossed)"
        elif p_crossed >= 20:
            a = p_safe_win
            b = p_safe - p_safe_win
            cwin = sum(1 for iid in ids if touches.get((iid, pL))
                       and touches[(iid, pL)]["book_crossed"] == "1"
                       and outs.get((iid, pL)) and outs[(iid, pL)]["win"] == 1)
            d = p_crossed - cwin
            pval = fisher_one_sided(a, b, cwin, d)
            g4 = f"{'PASS' if pval < 0.05 else 'FAIL'}(fisher_p={pval:.3f})"
        else:
            g4 = f"HOLD(crossed_n={p_crossed} in 1..19)"
        wl = wilson_lower(p_safe_win, p_safe)
        wl_ev = wl - pL / 1000.0
        g5 = "PASS" if (p_safe and wl_ev > 0) else f"{'FAIL' if p_safe else 'INSUFFICIENT'}({wl_ev*100:+.2f}c)"

        lines.append(f"    G0 EVIDENCE: FAIL(by-design: quote_proxy_can_pass=false)")
        lines.append(f"    G1 SAMPLE:{g1} | G2 ARM_DELTA:{g2} | G3 SAFE_WIN:{g3}")
        lines.append(f"    G4 CROSSED:{g4} | G5 WILSON_EV:{g5}")
        lines.append("")

    lines.append("gate_logic: all lines PASS or explicit G4 waiver, per asset×family; "
                 "NO pooled GO. This wave cannot reach GO (G0 by design).")
    return "\n".join(lines)
