"""R11 BLUE-X read-only audit.

All SQLite databases are opened through URI mode=ro.  The script never imports
or constructs KalshiLive.  Coinbase candles are obtained from the public
Exchange endpoint with curl.exe and kept in memory only.
"""

from __future__ import annotations

import json
import math
import random
import re
import sqlite3
import statistics
import subprocess
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
TICKS = Path(r"D:\kalshi-ticks")
DENVER = ZoneInfo("America/Denver")
NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc
MARK_MINUTES = (0, 2, 5, 8, 11, 15, 17, 20, 23, 26,
                30, 32, 35, 38, 41, 45, 47, 50, 53, 56)

# Git commit (committer) times.  These are the effective config times used by
# the running local process and are printed by the read-only command documented
# in the report.
ZONE_REGIMES = (
    (datetime.min, 0.85, 0.95, None),
    (datetime.fromisoformat("2026-07-04T10:27:19"), 0.86, 0.95, None),
    (datetime.fromisoformat("2026-07-04T12:25:49"), 0.86, 0.94, None),
    (datetime.fromisoformat("2026-07-04T20:53:19"), 0.84, 0.94, None),
    (datetime.fromisoformat("2026-07-08T09:31:47"), 0.86, 0.94, None),
    (datetime.fromisoformat("2026-07-08T21:28:46"), 0.86, 0.94, 0.90),
)


def ro(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    """Open a SQLite database read-only and make accidental writes fail."""
    suffix = "?mode=ro" + ("&immutable=1" if immutable else "")
    con = sqlite3.connect(path.resolve().as_uri() + suffix, uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def effective_zone(trade: dict) -> tuple[float, float]:
    ts = datetime.fromisoformat(trade.get("booked_ts") or trade["ts"])
    regime = ZONE_REGIMES[0]
    for candidate in ZONE_REGIMES:
        if ts >= candidate[0]:
            regime = candidate
    _, lo, hi, yes_lo = regime
    if trade["side"] == "yes" and yes_lo is not None:
        lo = max(lo, yes_lo)
    return lo, hi


def in_effective_zone(trade: dict) -> bool:
    lo, hi = effective_zone(trade)
    return lo <= float(trade["price"]) <= hi


def gross_settlement(trade: dict) -> float:
    payout = 1.0 if trade["result"] == trade["side"] else 0.0
    return float(trade["contracts"]) * (payout - float(trade["price"]))


def ratio_stats(rows: list[dict], value_fn) -> tuple[float, float, float]:
    """Per-contract ratio, cluster-robust SE, and t statistic by ledger row."""
    values = [float(value_fn(r)) for r in rows]
    weights = [float(r["contracts"]) for r in rows]
    mu = sum(values) / sum(weights)
    influence = [y - mu * w for y, w in zip(values, weights)]
    n = len(rows)
    se = math.sqrt(n / (n - 1) * sum(x * x for x in influence)) / sum(weights)
    return mu, se, mu / se


def cluster_bootstrap(rows: list[dict], value_fn, *, reps: int = 50_000,
                      seed: int = 56011) -> tuple[float, float]:
    """Percentile CI, resampling ledger rows and retaining row contract size."""
    rng = random.Random(seed)
    n = len(rows)
    out = []
    for _ in range(reps):
        total = cards = 0.0
        for _ in range(n):
            row = rows[rng.randrange(n)]
            total += float(value_fn(row))
            cards += float(row["contracts"])
        out.append(total / cards)
    out.sort()
    return out[int(0.025 * reps)], out[int(0.975 * reps)]


def q1() -> dict:
    with ro(ROOT / "data" / "ledger.db") as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM trades WHERE title LIKE 'favorite KX%' "
            "AND status IN ('settled','closed') ORDER BY id")]
    inside = [r for r in rows if in_effective_zone(r)]
    settled = [r for r in inside if r["status"] == "settled"]
    closed = [r for r in inside if r["status"] == "closed"]

    gross_mu, gross_se, gross_t = ratio_stats(settled, gross_settlement)
    gross_ci = cluster_bootstrap(settled, gross_settlement)
    settled_net_mu, _, settled_net_t = ratio_stats(
        settled, lambda r: r["pnl_usd"])
    settled_net_ci = cluster_bootstrap(
        settled, lambda r: r["pnl_usd"], seed=56012)
    all_mu, all_se, all_t = ratio_stats(inside, lambda r: r["pnl_usd"])
    all_ci = cluster_bootstrap(inside, lambda r: r["pnl_usd"], seed=56013)

    burden = {}
    for row in closed:
        series = row["ticker"].split("-")[0]
        b = burden.setdefault(series, {
            "events": 0, "contracts": 0.0, "entry_value": 0.0,
            "exit_value": 0.0, "gross_loss": 0.0, "fees_rounding": 0.0,
            "ledger_pnl": 0.0,
        })
        n = float(row["contracts"])
        gross = n * (float(row["exit_price"]) - float(row["price"]))
        b["events"] += 1
        b["contracts"] += n
        b["entry_value"] += n * float(row["price"])
        b["exit_value"] += n * float(row["exit_price"])
        b["gross_loss"] += gross
        b["ledger_pnl"] += float(row["pnl_usd"])
        b["fees_rounding"] += gross - float(row["pnl_usd"])

    return {
        "inside_events": len(inside),
        "inside_contracts": sum(float(r["contracts"]) for r in inside),
        "settled": {
            "events": len(settled),
            "contracts": sum(float(r["contracts"]) for r in settled),
            "gross_total": sum(gross_settlement(r) for r in settled),
            "gross_per_contract": gross_mu,
            "gross_se": gross_se,
            "gross_t": gross_t,
            "gross_ci": gross_ci,
            "net_total": sum(float(r["pnl_usd"]) for r in settled),
            "net_per_contract": settled_net_mu,
            "net_t": settled_net_t,
            "net_ci": settled_net_ci,
        },
        "with_guards": {
            "events": len(inside),
            "contracts": sum(float(r["contracts"]) for r in inside),
            "net_total": sum(float(r["pnl_usd"]) for r in inside),
            "net_per_contract": all_mu,
            "net_se": all_se,
            "net_t": all_t,
            "net_ci": all_ci,
        },
        "guard_burden": burden,
    }


def taker_fee(price: float, contracts: float) -> float:
    raw = 0.07 * contracts * price * (1.0 - price)
    return math.ceil(raw * 100 - 1e-9) / 100.0


def close_time_for_ticker(ticker: str) -> datetime | None:
    hourly = re.search(r"-26JUL(\d{2})(\d{2})-T", ticker)
    if hourly:
        day, hour = map(int, hourly.groups())
        return datetime(2026, 7, day, hour, tzinfo=NEW_YORK).astimezone(UTC)
    m15 = re.search(r"-26JUL(\d{2})(\d{2})(\d{2})-", ticker)
    if m15:
        day, hour, minute = map(int, m15.groups())
        return datetime(2026, 7, day, hour, minute,
                        tzinfo=NEW_YORK).astimezone(UTC)
    return None


def product_for_ticker(ticker: str) -> str | None:
    prefix = ticker.split("-")[0]
    for token, product in (("BTC", "BTC-USD"), ("ETH", "ETH-USD"),
                           ("SOL", "SOL-USD"), ("XRP", "XRP-USD")):
        if token in prefix:
            return product
    return None


def strike_for_ticker(ticker: str) -> float | None:
    match = re.search(r"-T([0-9.]+)$", ticker)
    return float(match.group(1)) if match else None


class TickBooks:
    def __init__(self) -> None:
        self.cons: dict[str, sqlite3.Connection] = {}

    def _con(self, day: str) -> sqlite3.Connection | None:
        if day in self.cons:
            return self.cons[day]
        path = TICKS / f"ticks_{day}.db"
        if not path.exists():
            return None
        con = ro(path, immutable=True)
        self.cons[day] = con
        return con

    def held_bid(self, ticker: str, side: str, when_utc: datetime,
                 tolerance_seconds: int = 50) -> tuple[datetime, float] | None:
        con = self._con(when_utc.strftime("%Y%m%d"))
        if con is None:
            return None
        a = (when_utc - timedelta(seconds=tolerance_seconds)).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        b = (when_utc + timedelta(seconds=tolerance_seconds)).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        target = when_utc.isoformat().replace("+00:00", "Z")
        row = con.execute(
            "SELECT ts,yes_bid,yes_ask FROM book WHERE ticker=? "
            "AND ts BETWEEN ? AND ? ORDER BY "
            "abs((julianday(ts)-julianday(?))*86400) LIMIT 1",
            (ticker, a, b, target)).fetchone()
        if row is None or not row["yes_bid"] or not row["yes_ask"]:
            return None
        bid = float(row["yes_bid"]) if side == "yes" else 1.0 - float(row["yes_ask"])
        return datetime.fromisoformat(row["ts"].replace("Z", "+00:00")), bid

    def final_result(self, ticker: str, close_utc: datetime) -> str | None:
        con = self._con(close_utc.strftime("%Y%m%d"))
        if con is None:
            return None
        a = (close_utc - timedelta(minutes=2)).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        b = close_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        row = con.execute(
            "SELECT yes_bid,yes_ask FROM book WHERE ticker=? AND ts BETWEEN ? AND ? "
            "AND yes_bid IS NOT NULL AND yes_ask IS NOT NULL ORDER BY ts DESC LIMIT 1",
            (ticker, a, b)).fetchone()
        if row is None:
            return None
        return "yes" if (float(row["yes_bid"]) + float(row["yes_ask"])) / 2 >= 0.5 else "no"

    def close(self) -> None:
        for con in self.cons.values():
            con.close()


class CoinbaseCandles:
    """Read-only in-memory cache of public one-minute Coinbase candles."""

    def __init__(self) -> None:
        self.blocks: dict[tuple[str, str, int], dict[int, list[float]]] = {}

    def _block(self, product: str, when: datetime) -> dict[int, list[float]]:
        when = when.astimezone(UTC)
        block_hour = (when.hour // 4) * 4
        key = (product, when.date().isoformat(), block_hour)
        if key in self.blocks:
            return self.blocks[key]
        start = when.replace(hour=block_hour, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=4, minutes=59)
        query = urllib.parse.urlencode({
            "granularity": 60,
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
        })
        url = f"https://api.exchange.coinbase.com/products/{product}/candles?{query}"
        last_error = ""
        for _ in range(3):
            proc = subprocess.run(
                ["curl.exe", "-sS", "--max-time", "20", "-H",
                 "User-Agent: r11-blue-x-readonly/1.0", url],
                capture_output=True, text=True, timeout=25, check=False)
            if proc.returncode == 0:
                try:
                    raw = json.loads(proc.stdout)
                    if isinstance(raw, list):
                        out = {int(x[0]): x for x in raw if isinstance(x, list) and len(x) >= 5}
                        self.blocks[key] = out
                        return out
                except json.JSONDecodeError as exc:
                    last_error = str(exc)
            else:
                last_error = proc.stderr.strip()
        raise RuntimeError(f"Coinbase candle fetch failed for {key}: {last_error}")

    def spot(self, product: str, when: datetime) -> float | None:
        candles = self._block(product, when)
        minute = int(when.astimezone(UTC).replace(second=0, microsecond=0).timestamp())
        row = candles.get(minute)
        return float(row[4]) if row else None  # one-minute close


def subsequent_guard_marks(first_local: datetime, close_utc: datetime,
                           scan_seconds: dict[tuple[str, int], float]):
    """Guard marks after the first trigger, using that day's observed loop phase."""
    close_local = close_utc.astimezone(DENVER).replace(tzinfo=None)
    cursor = first_local.replace(minute=0, second=0, microsecond=0)
    end = close_local + timedelta(minutes=1)
    while cursor <= end:
        for minute in MARK_MINUTES:
            nominal = cursor.replace(minute=minute, second=30)
            nominal_utc = nominal.replace(tzinfo=DENVER).astimezone(UTC)
            phase = scan_seconds.get((nominal_utc.date().isoformat(),
                                      nominal_utc.minute), 30.0)
            mark = nominal.replace(second=min(59, int(round(phase))))
            if mark > first_local + timedelta(seconds=45) and mark < close_local:
                yield mark
        cursor += timedelta(hours=1)


def q2() -> dict:
    with ro(ROOT / "data" / "ledger.db") as con:
        closed = [dict(r) for r in con.execute(
            "SELECT * FROM trades WHERE status='closed' "
            "AND lower(coalesce(rationale,'')) LIKE '%stopguard%' ORDER BY id")]
        special = {r["id"]: dict(r) for r in con.execute(
            "SELECT * FROM trades WHERE id IN (52,76,88)")}
    with ro(ROOT / "data" / "stop_shadow.db") as con:
        stops = {r["trade_id"]: dict(r) for r in con.execute(
            "SELECT * FROM stops")}
    with ro(ROOT / "data" / "market_calibration.db") as con:
        cal_result = {r["ticker"]: r["result"] for r in con.execute(
            "SELECT ticker,max(result) result FROM snaps "
            "WHERE result IN ('yes','no') GROUP BY ticker")}
    with ro(ROOT / "data" / "h10_shadow.db") as con:
        phase_rows = [r["ts"] for r in con.execute("SELECT ts FROM shadow")]
    phase_samples: dict[tuple[str, int], list[float]] = defaultdict(list)
    for value in phase_rows:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        phase_samples[(stamp.date().isoformat(), stamp.minute)].append(
            stamp.second + stamp.microsecond / 1e6)
    scan_seconds = {k: statistics.median(v) for k, v in phase_samples.items()}

    books = TickBooks()
    candles = CoinbaseCandles()

    def replay(trade: dict) -> dict:
        stop = stops.get(trade["id"])
        close_utc = close_time_for_ticker(trade["ticker"])
        product = product_for_ticker(trade["ticker"])
        strike = (float(stop["strike"]) if stop and stop.get("strike") is not None
                  else strike_for_ticker(trade["ticker"]))
        result = trade.get("result") if trade.get("result") in ("yes", "no") else None
        result_source = "ledger" if result is not None else None
        if result is None:
            result = cal_result.get(trade["ticker"])
            if result is not None:
                result_source = "market_calibration"
        if result is None and close_utc is not None:
            result = books.final_result(trade["ticker"], close_utc)
            if result is not None:
                result_source = "final_tick"
        # A few hourly tick streams end early or straddle the UTC file boundary.
        # For T-strike markets only, Coinbase's last one-minute close supplies a
        # documented approximation of the settlement direction.
        if result is None and close_utc is not None and product is not None \
                and strike is not None:
            try:
                closing_spot = candles.spot(product, close_utc - timedelta(seconds=1))
            except RuntimeError:
                closing_spot = None
            if closing_spot is not None:
                result = "yes" if closing_spot > strike else "no"
                result_source = "coinbase_close_proxy"
        hold = None if result is None else (
            (float(trade["contracts"]) if result == trade["side"] else 0.0)
            - float(trade["cost_usd"]))
        base = {
            "id": trade["id"], "ticker": trade["ticker"], "side": trade["side"],
            "actual_pnl": float(trade["pnl_usd"] or 0.0), "hold_pnl": hold,
            "result": result, "result_source": result_source,
            "first_stop_ts": stop["ts"] if stop else None,
            "fire_ts": None, "fire_bid": None, "fire_type": None,
            "delay_minutes": None, "repaired_pnl": hold, "reason": None,
            "post_mark_count": 0, "post_quote_count": 0,
        }
        if stop is None or close_utc is None or product is None or strike is None:
            base["reason"] = "missing stop/close/product/strike"
            base["repaired_pnl"] = None
            return base
        first_local = datetime.fromisoformat(stop["ts"])
        first_spot = float(stop["spot"]) if stop.get("spot") is not None else None
        samples = [(first_local, float(stop["held_bid"]), first_spot, True)]
        for mark in subsequent_guard_marks(first_local, close_utc, scan_seconds):
            base["post_mark_count"] += 1
            utc_mark = mark.replace(tzinfo=DENVER).astimezone(UTC)
            quote = books.held_bid(trade["ticker"], trade["side"], utc_mark)
            if quote is None:
                continue
            base["post_quote_count"] += 1
            try:
                spot = candles.spot(product, utc_mark)
            except RuntimeError:
                spot = None
            samples.append((mark, quote[1], spot, False))

        streak = 0
        for when_local, bid, spot, observed in samples:
            if not (0 < bid <= 0.70) or spot is None:
                streak = 0
                continue
            direct = spot < strike if trade["side"] == "yes" else spot > strike
            near = abs(spot - strike) / strike <= 0.0005
            if direct:
                fire_type = "cross-direct"
            elif near:
                streak += 1
                if streak < 2:
                    continue
                fire_type = "two-tick-near"
            else:
                streak = 0
                continue
            fee = taker_fee(bid, float(trade["contracts"]))
            repaired = float(trade["contracts"]) * bid - fee - float(trade["cost_usd"])
            base.update({
                "fire_ts": when_local.isoformat(timespec="seconds"),
                "fire_bid": bid,
                "fire_type": fire_type,
                "delay_minutes": (when_local - first_local).total_seconds() / 60,
                "repaired_pnl": repaired,
                "reason": "first observed tick" if observed else "tick replay",
            })
            break
        if base["fire_ts"] is None and base["reason"] is None:
            if base["post_mark_count"] and not base["post_quote_count"]:
                base["reason"] = "unresolved: no post-trigger Kalshi ticks"
                base["repaired_pnl"] = None
            else:
                base["reason"] = "no repaired-rule fire; hold to settlement"
        return base

    rows = [replay(r) for r in closed]
    specials = []
    for trade_id in (52, 76, 88):
        trade = special[trade_id]
        # These rows settled normally, so the actual column is their ledger P&L.
        item = replay(trade)
        item["actual_pnl"] = float(trade["pnl_usd"] or 0.0)
        specials.append(item)
    books.close()

    complete = [r for r in rows if r["repaired_pnl"] is not None and r["hold_pnl"] is not None]
    return {
        "events": rows,
        "summary": {
            "n": len(rows),
            "n_complete": len(complete),
            "actual": sum(r["actual_pnl"] for r in complete),
            "repaired": sum(r["repaired_pnl"] for r in complete),
            "hold": sum(r["hold_pnl"] for r in complete),
            "fires": sum(r["fire_ts"] is not None for r in complete),
            "no_fires": sum(r["fire_ts"] is None for r in complete),
            "direct": sum(r["fire_type"] == "cross-direct" for r in complete),
            "two_tick": sum(r["fire_type"] == "two-tick-near" for r in complete),
        },
        "special": specials,
    }


def q3() -> dict:
    """Compare H13 rows with raw tick quotes at inferred real scan seconds."""
    with ro(ROOT / "data" / "h10_shadow.db") as con:
        shadow = [dict(r) for r in con.execute("SELECT * FROM shadow")]

    seconds: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in shadow:
        stamp = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        seconds[(stamp.date().isoformat(), stamp.minute)].append(
            stamp.second + stamp.microsecond / 1e6)
    scan_second = {k: statistics.median(v) for k, v in seconds.items()}
    btc_rows = {r["ticker"]: r for r in shadow if r["series"] == "KXBTC15M"}
    observed = [r for r in btc_rows.values()
                if float(r["tau_min"] or 0) <= 6 and r["result"] in ("yes", "no")]
    # Freeze the raw-tick comparison at the close time of the 46th observed row;
    # the live collectors continue writing while this audit runs.
    cutoff = max(r["close_time"] for r in observed)
    with ro(ROOT / "data" / "market_calibration.db") as con:
        markets = [dict(r) for r in con.execute(
            "SELECT ticker,min(close_time) close_time,max(result) result FROM snaps "
            "WHERE series='KXBTC15M' AND result IN ('yes','no') "
            "AND close_time BETWEEN '2026-07-05T00:00:00Z' AND ? "
            "GROUP BY ticker ORDER BY close_time", (cutoff,))]

    books = TickBooks()
    eligible = []
    for market in markets:
        close = datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
        mark = close - timedelta(minutes=4)
        key = (mark.date().isoformat(), mark.minute)
        if key not in scan_second:
            continue
        target = mark.replace(second=int(round(scan_second[key])), microsecond=0)
        con = books._con(close.strftime("%Y%m%d"))
        if con is None:
            continue
        a = (target - timedelta(seconds=2)).isoformat().replace("+00:00", "Z")
        b = (target + timedelta(seconds=2)).isoformat().replace("+00:00", "Z")
        target_iso = target.isoformat().replace("+00:00", "Z")
        tick = con.execute(
            "SELECT ts,yes_bid,yes_ask FROM book WHERE ticker=? AND ts BETWEEN ? AND ? "
            "ORDER BY abs((julianday(ts)-julianday(?))*86400) LIMIT 1",
            (market["ticker"], a, b, target_iso)).fetchone()
        if tick is None or not tick["yes_bid"] or not tick["yes_ask"]:
            continue
        mid = (float(tick["yes_bid"]) + float(tick["yes_ask"])) / 2
        side = "yes" if mid >= 0.5 else "no"
        ask = float(tick["yes_ask"]) if side == "yes" else 1 - float(tick["yes_bid"])
        if not (0.94 <= ask <= 0.985):
            continue
        old = btc_rows.get(market["ticker"])
        status = ("missing" if old is None else
                  "final6" if float(old["tau_min"] or 0) <= 6 else "main-pk")
        won = side == market["result"]
        eligible.append({
            "ticker": market["ticker"], "scan_ts": tick["ts"], "side": side,
            "ask": ask, "result": market["result"], "won": won,
            "shadow_status": status, "net": (1.0 if won else 0.0) - ask - 0.01,
        })
    books.close()

    observed_net = sum((1.0 if r["result"] == r["side"] else 0.0)
                       - float(r["ask"]) - float(r["fee"]) for r in observed)
    return {
        "observed": {
            "n": len(observed),
            "wins": sum(r["result"] == r["side"] for r in observed),
            "net": observed_net,
            "mean": observed_net / len(observed),
        },
        "tick_audit": {
            "cutoff": cutoff,
            "n": len(eligible),
            "wins": sum(r["won"] for r in eligible),
            "losses": sum(not r["won"] for r in eligible),
            "net": sum(r["net"] for r in eligible),
            "mean": sum(r["net"] for r in eligible) / len(eligible),
            "coverage": len(observed) / len(eligible),
            "by_status": {
                status: {
                    "n": sum(r["shadow_status"] == status for r in eligible),
                    "wins": sum(r["shadow_status"] == status and r["won"]
                                for r in eligible),
                    "net": sum(r["net"] for r in eligible
                               if r["shadow_status"] == status),
                }
                for status in ("final6", "main-pk", "missing")
            },
            "loss_rows": [r for r in eligible if not r["won"]],
        },
    }


def main() -> None:
    print("Q1")
    print(json.dumps(q1(), ensure_ascii=False, indent=2))
    print("Q2")
    print(json.dumps(q2(), ensure_ascii=False, indent=2))
    print("Q3")
    print(json.dumps(q3(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
