#!/usr/bin/env python3
"""
Preregistered τ-exit backtest.

Inputs are opened through SQLite URI mode=ro. The script never modifies a
database or config file. It writes only:

    <out>/tau_exit_backtest.json
    <out>/tau_exit_backtest.md
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import random
import re
import sqlite3
import statistics
import sys
from pathlib import Path
from urllib.parse import quote


SPEC_PATH = Path(r"D:\Polymarket-Kelshi\research\TAU_EXIT_SPEC_2026-07-12.md")
CONFIG_PATH = Path(r"D:\Polymarket-Kelshi\config.yaml")
LEDGER_PATH = Path(r"D:\Polymarket-Kelshi\data\ledger.db")
TICK_DIR = Path(r"D:\kalshi-ticks")
START_TS = "2026-07-05"

SUPPORTED_SERIES = {"KXBTCD", "KXETHD", "KXSOLD", "KXXRPD"}
MONTHS = {
    name: number
    for number, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
         "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        1,
    )
}

# Frozen preregistration/config values. None are CLI options.
WINDOW_SECONDS = 60 * 60
LATE_SECONDS = WINDOW_SECONDS / 3
BID_TRIGGER = 0.70
PROXIMITY_PCT = {
    "calm": 0.05,
    "elevated": 0.075,
    "storm": 0.10,
}
REGIME_CALM_MAX = 0.02727
REGIME_STORM_MIN = 0.03709
TAKE_PROFIT_CAPTURE = 0.60
MIN_TARGET_MOVE = 0.03
EXIT_CROSS = 0.02

BOOTSTRAP_REPS = 10_000
BOOTSTRAP_SEED = 20260712

# Data-quality rules, not strategy parameters.
COVERAGE_GAP_MULTIPLIER = 5.0
COVERAGE_GAP_FLOOR_S = 5.0

UTC = dt.timezone.utc

MACRO_WINDOWS = tuple(
    (
        dt.datetime.fromisoformat(start.replace("Z", "+00:00")),
        dt.datetime.fromisoformat(end.replace("Z", "+00:00")),
    )
    for start, end in (
        ("2026-07-08T17:30:00Z", "2026-07-08T19:30:00Z"),
        ("2026-07-14T12:00:00Z", "2026-07-14T14:00:00Z"),
        ("2026-07-29T17:30:00Z", "2026-07-29T20:00:00Z"),
        ("2026-07-30T12:00:00Z", "2026-07-30T14:00:00Z"),
        ("2026-08-07T12:00:00Z", "2026-08-07T14:00:00Z"),
        ("2026-08-12T12:00:00Z", "2026-08-12T14:00:00Z"),
        ("2026-08-19T17:30:00Z", "2026-08-19T19:30:00Z"),
        ("2026-08-26T12:00:00Z", "2026-08-26T14:00:00Z"),
    )
)


def iso_utc(value: dt.datetime, timespec: str = "milliseconds") -> str:
    return (
        value.astimezone(UTC)
        .isoformat(timespec=timespec)
        .replace("+00:00", "Z")
    )


def parse_tick_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(
        value.replace("Z", "+00:00")
    ).astimezone(UTC)


def first_sunday(year: int, month: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(6 - first.weekday()) % 7)


def us_dst_active(local_naive: dt.datetime) -> bool:
    """US DST: second Sunday in March through first Sunday in November."""
    start_day = first_sunday(local_naive.year, 3) + dt.timedelta(days=7)
    end_day = first_sunday(local_naive.year, 11)
    start = dt.datetime.combine(start_day, dt.time(2, 0))
    end = dt.datetime.combine(end_day, dt.time(2, 0))
    return start <= local_naive < end


def wall_time_to_utc(
    local_naive: dt.datetime,
    standard_offset_hours: int,
) -> dt.datetime:
    offset_hours = standard_offset_hours
    if us_dst_active(local_naive):
        offset_hours += 1
    return (
        local_naive - dt.timedelta(hours=offset_hours)
    ).replace(tzinfo=UTC)


def parse_ledger_time(value: str | None) -> dt.datetime | None:
    """
    Production writes naive datetime.now() values. On this host they are
    America/Denver wall times. Aware values retain their explicit offset.
    """
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return wall_time_to_utc(parsed, standard_offset_hours=-7)
    return parsed.astimezone(UTC)


def day_range(
    start: dt.datetime,
    end_exclusive: dt.datetime,
) -> list[dt.date]:
    if end_exclusive <= start:
        return []
    final_day = (end_exclusive - dt.timedelta(microseconds=1)).date()
    current = start.date()
    result = []
    while current <= final_day:
        result.append(current)
        current += dt.timedelta(days=1)
    return result


def sqlite_uri(path: Path, immutable: bool = False) -> str:
    posix = path.resolve().as_posix()
    uri = f"file:{quote(posix, safe='/:')}?mode=ro"
    if immutable:
        uri += "&immutable=1"
    return uri


def connect_readonly(
    path: Path,
    allow_historical_immutable: bool = False,
) -> tuple[sqlite3.Connection, str]:
    try:
        connection = sqlite3.connect(
            sqlite_uri(path),
            uri=True,
            timeout=30,
        )
        open_mode = "mode=ro"
    except sqlite3.OperationalError as first_error:
        match = re.search(r"ticks_(\d{8})\.db$", path.name)
        historical = False
        if match:
            database_day = dt.datetime.strptime(
                match.group(1), "%Y%m%d"
            ).date()
            historical = database_day < dt.datetime.now(UTC).date()

        if not (allow_historical_immutable and historical):
            raise first_error

        connection = sqlite3.connect(
            sqlite_uri(path, immutable=True),
            uri=True,
            timeout=30,
        )
        open_mode = "mode=ro&immutable=1 historical fallback"

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection, open_mode


def table_columns(
    connection: sqlite3.Connection,
    table: str,
) -> list[str]:
    safe = table.replace('"', '""')
    return [
        row[1]
        for row in connection.execute(
            f'PRAGMA table_info("{safe}")'
        )
    ]


def audit_config() -> dict:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    expected = {
        "take_profit_capture": TAKE_PROFIT_CAPTURE,
        "regime_calm_max": REGIME_CALM_MAX,
        "regime_storm_min": REGIME_STORM_MIN,
        "bid_trigger": BID_TRIGGER,
        "spot_proximity_pct": PROXIMITY_PCT["calm"],
        "elevated_proximity_pct": PROXIMITY_PCT["elevated"],
        "storm_proximity_pct": PROXIMITY_PCT["storm"],
        "exit_cross": EXIT_CROSS,
    }
    patterns = {
        "take_profit_capture":
            r"(?m)^\s{2}take_profit_capture:\s*([0-9.]+)",
        "regime_calm_max":
            r"(?m)^regime_calm_max:\s*([0-9.]+)",
        "regime_storm_min":
            r"(?m)^regime_storm_min:\s*([0-9.]+)",
        "bid_trigger":
            r"(?m)^\s{2}bid_trigger:\s*([0-9.]+)",
        "spot_proximity_pct":
            r"(?m)^\s{2}spot_proximity_pct:\s*([0-9.]+)",
        "elevated_proximity_pct":
            r"(?m)^\s{2}elevated_proximity_pct:\s*([0-9.]+)",
        "storm_proximity_pct":
            r"(?m)^\s{2}storm_proximity_pct:\s*([0-9.]+)",
        "exit_cross":
            r"(?m)^\s{2}exit_cross:\s*([0-9.]+)",
    }

    observed = {}
    checks = {}
    for key, expected_value in expected.items():
        match = re.search(patterns[key], text)
        observed[key] = float(match.group(1)) if match else None
        checks[key] = (
            observed[key] is not None
            and math.isclose(
                observed[key],
                expected_value,
                abs_tol=1e-12,
            )
        )

    return {
        "expected_frozen": expected,
        "observed": observed,
        "checks": checks,
        "all_match": all(checks.values()),
    }


def parse_contract(ticker: str) -> dict | None:
    parts = ticker.split("-")
    if len(parts) < 3 or parts[0] not in SUPPORTED_SERIES:
        return None

    segment = parts[1]
    if not re.fullmatch(r"\d{2}[A-Z]{3}\d{4}", segment):
        return None

    strike_match = re.search(
        r"-T([0-9]+(?:\.[0-9]+)?)$",
        ticker,
    )
    if not strike_match:
        return None

    try:
        local_close = dt.datetime(
            2000 + int(segment[0:2]),
            MONTHS[segment[2:5]],
            int(segment[5:7]),
            int(segment[7:9]),
            0,
        )
        close_utc = wall_time_to_utc(
            local_close,
            standard_offset_hours=-5,
        )
        strike = float(strike_match.group(1))
    except (KeyError, ValueError):
        return None

    return {
        "series": parts[0],
        "strike": strike,
        "close_utc": close_utc,
        "window_seconds": WINDOW_SECONDS,
        "cluster_key": ticker.rsplit("-", 1)[0],
    }


def side_quote(
    row: dict,
    side: str,
) -> tuple[float | None, float | None]:
    if side == "yes":
        price = row.get("yes_bid")
        depth = row.get("bid_sz")
    else:
        yes_ask = row.get("yes_ask")
        price = (
            None
            if yes_ask is None
            else round(1.0 - float(yes_ask), 4)
        )
        depth = row.get("ask_sz")

    try:
        price = None if price is None else float(price)
        depth = None if depth is None else float(depth)
    except (TypeError, ValueError):
        return None, None

    if (
        price is None
        or not math.isfinite(price)
        or not 0.0 < price < 1.0
    ):
        price = None

    if depth is not None and (
        not math.isfinite(depth) or depth < 0
    ):
        depth = None

    return price, depth


def yes_probability(bid, ask) -> float | None:
    try:
        bid = None if bid is None else float(bid)
        ask = None if ask is None else float(ask)
    except (TypeError, ValueError):
        return None

    if (
        bid is not None
        and ask is not None
        and 0 <= bid <= ask <= 1
    ):
        return (bid + ask) / 2.0

    # One-sided quotes are used only when they prove the side of 0.5.
    if bid is not None and 0.5 <= bid <= 1:
        return bid
    if ask is not None and 0 <= ask <= 0.5:
        return ask
    return None


def taker_fee(price: float, contracts: float) -> float:
    raw = 0.07 * contracts * price * (1.0 - price)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def regime_at(when: dt.datetime) -> str:
    if any(start <= when <= end for start, end in MACRO_WINDOWS):
        return "storm"

    # Tick schema lacks the 24h spot-candle composite. This matches the
    # production fail-safe for blind/stale RV data.
    return "elevated"


class TickStore:
    REQUIRED_COLUMNS = {
        "ts",
        "ticker",
        "yes_bid",
        "yes_ask",
        "bid_sz",
        "ask_sz",
        "l2_json",
        "l3_json",
        "last_trade_px",
        "seq",
    }

    def __init__(self, root: Path):
        self.root = root
        self.files: dict[dt.date, Path] = {}
        for path in sorted(root.glob("ticks_*.db")):
            match = re.fullmatch(r"ticks_(\d{8})\.db", path.name)
            if match:
                day = dt.datetime.strptime(
                    match.group(1), "%Y%m%d"
                ).date()
                self.files[day] = path

        self.connections: dict[dt.date, sqlite3.Connection] = {}
        self.open_modes: dict[str, str] = {}
        self.index_ok: dict[dt.date, bool] = {}
        self.schema_audit: dict[str, dict] = {}
        self.query_plans: dict[str, str] = {}
        self.warnings: set[str] = set()

        self.ladder_cache: dict[
            tuple[dt.date, str],
            list[tuple[float, str]],
        ] = {}
        self.proxy_cache: dict[
            tuple[dt.date, str, str],
            float | None,
        ] = {}
        self.prepared_no_index_ranges: dict[
            tuple[dt.date, str],
            tuple[dt.datetime, dt.datetime],
        ] = {}

    def connection(self, day: dt.date) -> sqlite3.Connection:
        if day in self.connections:
            return self.connections[day]

        path = self.files.get(day)
        if path is None:
            raise FileNotFoundError(
                f"missing tick database for {day.isoformat()}"
            )

        connection, open_mode = connect_readonly(
            path,
            allow_historical_immutable=True,
        )

        columns = table_columns(connection, "book")
        missing = sorted(self.REQUIRED_COLUMNS - set(columns))
        if missing:
            connection.close()
            raise RuntimeError(
                f"{path}: book schema missing {missing}"
            )

        indexes = []
        ticker_ts_index = False
        for row in connection.execute(
            'PRAGMA index_list("book")'
        ):
            name = row[1]
            safe = name.replace('"', '""')
            index_columns = [
                item[2]
                for item in connection.execute(
                    f'PRAGMA index_info("{safe}")'
                )
            ]
            indexes.append({
                "name": name,
                "columns": index_columns,
                "unique": bool(row[2]),
            })
            if index_columns[:2] == ["ticker", "ts"]:
                ticker_ts_index = True

        if not ticker_ts_index:
            self.warnings.add(
                f"{path.name}: no (ticker,ts) index; "
                "using one logical ts-range table scan per required window"
            )

        key = day.isoformat()
        self.connections[day] = connection
        self.open_modes[key] = open_mode
        self.index_ok[day] = ticker_ts_index
        self.schema_audit[key] = {
            "path": str(path),
            "columns": columns,
            "indexes": indexes,
            "ticker_ts_index": ticker_ts_index,
        }
        return connection

    def record_path_plan(
        self,
        day: dt.date,
        connection: sqlite3.Connection,
    ) -> None:
        key = f"path:{day.isoformat()}"
        if key in self.query_plans:
            return
        plan = connection.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT ts,yes_bid FROM book "
            "WHERE ticker=? AND ts>=? AND ts<? ORDER BY ts",
            ("__probe__", "0000", "9999"),
        ).fetchall()
        self.query_plans[key] = " | ".join(
            str(row[3]) for row in plan
        )

    def load_path(
        self,
        ticker: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> tuple[list[dict] | None, dict]:
        days = day_range(start, end)
        missing_days = [
            day.isoformat()
            for day in days
            if day not in self.files
        ]
        coverage = {
            "required_days": [
                day.isoformat() for day in days
            ],
            "missing_days": missing_days,
        }

        if missing_days:
            coverage["reason"] = "missing_tick_day"
            return None, coverage

        projection = (
            "ts,yes_bid,yes_ask,bid_sz,ask_sz,"
            "last_trade_px,seq"
        )
        rows: list[dict] = []

        for day in days:
            connection = self.connection(day)
            self.record_path_plan(day, connection)

            day_start = dt.datetime.combine(
                day,
                dt.time.min,
                tzinfo=UTC,
            )
            day_end = day_start + dt.timedelta(days=1)
            lower = max(start, day_start)
            upper = min(end, day_end)

            sql = (
                f"SELECT {projection} FROM book "
                "WHERE ticker=? AND ts>=? AND ts<?"
            )
            if self.index_ok[day]:
                sql += " ORDER BY ts"

            for raw in connection.execute(
                sql,
                (ticker, iso_utc(lower), iso_utc(upper)),
            ):
                item = dict(raw)
                item["_dt"] = parse_tick_time(item["ts"])
                rows.append(item)

        rows.sort(key=lambda item: item["_dt"])

        deduplicated = []
        seen_timestamps = set()
        for row in rows:
            if row["ts"] not in seen_timestamps:
                deduplicated.append(row)
                seen_timestamps.add(row["ts"])
        rows = deduplicated

        if not rows:
            coverage["reason"] = "ticker_path_empty"
            return None, coverage

        times = [row["_dt"] for row in rows]
        gaps = [
            (right - left).total_seconds()
            for left, right in zip(times, times[1:])
            if right > left
        ]
        cadence = statistics.median(gaps) if gaps else None
        allowed_gap = (
            max(
                COVERAGE_GAP_FLOOR_S,
                COVERAGE_GAP_MULTIPLIER * cadence,
            )
            if cadence is not None
            else COVERAGE_GAP_FLOOR_S
        )
        start_gap = max(
            0.0,
            (times[0] - start).total_seconds(),
        )
        end_gap = max(
            0.0,
            (end - times[-1]).total_seconds(),
        )
        max_internal_gap = max(gaps, default=0.0)

        coverage.update({
            "rows": len(rows),
            "first_tick": rows[0]["ts"],
            "last_tick": rows[-1]["ts"],
            "median_cadence_s": (
                None if cadence is None else round(cadence, 3)
            ),
            "allowed_gap_s": round(allowed_gap, 3),
            "start_gap_s": round(start_gap, 3),
            "end_gap_s": round(end_gap, 3),
            "max_internal_gap_s": round(max_internal_gap, 3),
        })

        if (
            start_gap > allowed_gap
            or end_gap > allowed_gap
            or max_internal_gap > allowed_gap
        ):
            coverage["reason"] = "incomplete_tick_coverage"
            return None, coverage

        return rows, coverage

    @staticmethod
    def interpolate_crossing(
        points: list[tuple[float, float]],
    ) -> float | None:
        if len(points) < 2:
            return None

        by_strike = {}
        for strike, probability in points:
            by_strike[strike] = probability
        ordered = sorted(by_strike.items())

        for strike, probability in ordered:
            if math.isclose(
                probability,
                0.5,
                abs_tol=1e-12,
            ):
                return strike

        for (left_strike, left_p), (
            right_strike,
            right_p,
        ) in zip(ordered, ordered[1:]):
            if not (
                left_p >= 0.5 >= right_p
                and left_p >= right_p
            ):
                continue
            if math.isclose(left_p, right_p, abs_tol=1e-12):
                return (left_strike + right_strike) / 2.0
            return (
                left_strike
                + (0.5 - left_p)
                * (right_strike - left_strike)
                / (right_p - left_p)
            )

        return None

    def prepare_no_index_proxy_range(
        self,
        window_key: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> None:
        """
        With no ticker index, scan each required time range once. Never perform
        thousands of repeated full-table point scans.
        """
        for day in day_range(start, end):
            connection = self.connection(day)
            if self.index_ok[day]:
                continue

            day_start = dt.datetime.combine(
                day,
                dt.time.min,
                tzinfo=UTC,
            )
            day_end = day_start + dt.timedelta(days=1)
            requested_start = max(start, day_start)
            requested_end = min(end, day_end)

            range_key = (day, window_key)
            previous = self.prepared_no_index_ranges.get(range_key)
            if (
                previous
                and previous[0] <= requested_start
                and previous[1] >= requested_end
            ):
                continue

            scan_start = (
                min(previous[0], requested_start)
                if previous
                else requested_start
            )
            scan_end = (
                max(previous[1], requested_end)
                if previous
                else requested_end
            )

            snapshots: dict[
                str,
                list[tuple[float, float]],
            ] = collections.defaultdict(list)
            pattern = window_key + "-T*"

            sql = (
                "SELECT ts,ticker,yes_bid,yes_ask "
                "FROM book "
                "WHERE ts>=? AND ts<? AND ticker GLOB ?"
            )
            for row in connection.execute(
                sql,
                (
                    iso_utc(scan_start),
                    iso_utc(scan_end),
                    pattern,
                ),
            ):
                strike_match = re.search(
                    r"-T([0-9]+(?:\.[0-9]+)?)$",
                    row["ticker"],
                )
                probability = yes_probability(
                    row["yes_bid"],
                    row["yes_ask"],
                )
                if strike_match and probability is not None:
                    snapshots[row["ts"]].append(
                        (
                            float(strike_match.group(1)),
                            probability,
                        )
                    )

            for timestamp, points in snapshots.items():
                self.proxy_cache[
                    (day, window_key, timestamp)
                ] = self.interpolate_crossing(points)

            self.prepared_no_index_ranges[range_key] = (
                scan_start,
                scan_end,
            )

    def ladder(
        self,
        day: dt.date,
        window_key: str,
    ) -> list[tuple[float, str]]:
        cache_key = (day, window_key)
        if cache_key in self.ladder_cache:
            return self.ladder_cache[cache_key]

        connection = self.connection(day)
        pattern = window_key + "-T*"

        plan_key = f"ladder:{day.isoformat()}"
        if plan_key not in self.query_plans:
            plan = connection.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT DISTINCT ticker FROM book "
                "WHERE ticker GLOB ?",
                (pattern,),
            ).fetchall()
            self.query_plans[plan_key] = " | ".join(
                str(row[3]) for row in plan
            )

        result = []
        for row in connection.execute(
            "SELECT DISTINCT ticker FROM book "
            "WHERE ticker GLOB ? ORDER BY ticker",
            (pattern,),
        ):
            match = re.search(
                r"-T([0-9]+(?:\.[0-9]+)?)$",
                row[0],
            )
            if match:
                result.append(
                    (float(match.group(1)), row[0])
                )

        result.sort()
        self.ladder_cache[cache_key] = result
        return result

    def implied_spot(
        self,
        day: dt.date,
        window_key: str,
        tick_ts: str,
    ) -> float | None:
        cache_key = (day, window_key, tick_ts)
        if cache_key in self.proxy_cache:
            return self.proxy_cache[cache_key]

        connection = self.connection(day)
        if not self.index_ok[day]:
            # The caller must preload the time range once.
            self.proxy_cache[cache_key] = None
            return None

        ladder = self.ladder(day, window_key)
        if len(ladder) < 2:
            self.proxy_cache[cache_key] = None
            return None

        local_probabilities: dict[int, float | None] = {}

        def probability(index: int) -> float | None:
            if index not in local_probabilities:
                row = connection.execute(
                    "SELECT yes_bid,yes_ask FROM book "
                    "WHERE ticker=? AND ts=? LIMIT 1",
                    (ladder[index][1], tick_ts),
                ).fetchone()
                local_probabilities[index] = (
                    None
                    if row is None
                    else yes_probability(row[0], row[1])
                )
            return local_probabilities[index]

        left = 0
        right = len(ladder) - 1
        left_p = probability(left)
        right_p = probability(right)

        if (
            left_p is None
            or right_p is None
            or left_p < 0.5
            or right_p > 0.5
        ):
            self.proxy_cache[cache_key] = None
            return None

        while right - left > 1:
            middle = (left + right) // 2
            middle_p = probability(middle)
            if middle_p is None:
                self.proxy_cache[cache_key] = None
                return None
            if middle_p >= 0.5:
                left = middle
            else:
                right = middle

        left_p = probability(left)
        right_p = probability(right)
        if (
            left_p is None
            or right_p is None
            or left_p < 0.5
            or right_p > 0.5
            or left_p < right_p
        ):
            self.proxy_cache[cache_key] = None
            return None

        left_strike = ladder[left][0]
        right_strike = ladder[right][0]

        if math.isclose(left_p, right_p, abs_tol=1e-12):
            implied = (
                (left_strike + right_strike) / 2.0
                if math.isclose(left_p, 0.5, abs_tol=1e-12)
                else None
            )
        else:
            implied = (
                left_strike
                + (0.5 - left_p)
                * (right_strike - left_strike)
                / (right_p - left_p)
            )

        if implied is not None and not (
            left_strike - 1e-9
            <= implied
            <= right_strike + 1e-9
        ):
            implied = None

        self.proxy_cache[cache_key] = implied
        return implied

    def close(self) -> None:
        for connection in self.connections.values():
            connection.close()


def target_for_trade(
    trade: dict,
) -> tuple[float | None, str]:
    existing = trade.get("target_price")
    try:
        existing = (
            float(existing)
            if existing is not None
            else 0.0
        )
    except (TypeError, ValueError):
        existing = 0.0

    if existing > 0:
        return existing, "ledger_target"

    try:
        consensus = float(trade["q_consensus"])
    except (KeyError, TypeError, ValueError):
        return None, "q_missing"

    title = str(trade.get("title") or "")
    held_side_frame = title.startswith(
        ("favorite", "h10fav15m", "h15maker")
    )
    if held_side_frame or trade["side"] == "yes":
        q_side = consensus
    else:
        q_side = 1.0 - consensus

    entry = float(trade["price"])
    gap = q_side - entry
    target = round(
        min(
            entry + TAKE_PROFIT_CAPTURE * gap,
            0.99,
        ),
        4,
    )

    if (
        gap <= 0
        or target - entry < MIN_TARGET_MOVE
    ):
        return None, "no_registered_capture_target"

    return target, "recomputed_registered_0.6_capture"


def classify_cell(
    when: dt.datetime,
    close: dt.datetime,
    implied_spot: float,
    strike: float,
    side: str,
) -> dict:
    tau_seconds = max(
        0.0,
        (close - when).total_seconds(),
    )
    timing = (
        "late"
        if tau_seconds <= LATE_SECONDS
        else "early"
    )
    regime = regime_at(when)
    threshold_pct = PROXIMITY_PCT[regime]
    distance_pct = (
        abs(implied_spot - strike)
        / strike
        * 100.0
    )
    near = distance_pct <= threshold_pct
    losing = (
        implied_spot < strike
        if side == "yes"
        else implied_spot > strike
    )

    return {
        "cell": f"{timing}_{'near' if near else 'far'}",
        "timing": timing,
        "near": near,
        "losing": losing,
        "regime": regime,
        "proximity_threshold_pct": threshold_pct,
        "proxy_distance_pct": distance_pct,
        "tau_seconds": tau_seconds,
    }


def find_fill(
    rows: list[dict],
    start_index: int,
    side: str,
    contracts: float,
    action: str,
) -> dict | None:
    for index in range(start_index, len(rows)):
        row = rows[index]
        bid, displayed_depth = side_quote(row, side)
        if (
            bid is None
            or displayed_depth is None
            or displayed_depth + 1e-9 < contracts
        ):
            continue

        fill_price = (
            max(bid - EXIT_CROSS, 0.01)
            if action == "dual_stop"
            else bid
        )
        return {
            "ts": row["ts"],
            "price": round(fill_price, 4),
            "raw_bid": bid,
            "displayed_depth": displayed_depth,
            "latency_tick_rows": index - start_index + 1,
        }

    return None


def detect_open_cell(
    trade: dict,
    meta: dict,
    rows: list[dict],
    store: TickStore,
) -> dict:
    missing_proxy_candidates = 0

    for index, row in enumerate(rows):
        when = row["_dt"]
        tau_seconds = (
            meta["close_utc"] - when
        ).total_seconds()
        if tau_seconds <= LATE_SECONDS:
            continue

        held_bid, _ = side_quote(row, trade["side"])
        if (
            held_bid is None
            or not held_bid < BID_TRIGGER
        ):
            continue

        implied = store.implied_spot(
            when.date(),
            meta["cluster_key"],
            row["ts"],
        )
        if implied is None:
            missing_proxy_candidates += 1
            continue

        state = classify_cell(
            when,
            meta["close_utc"],
            implied,
            meta["strike"],
            trade["side"],
        )
        if not state["near"]:
            continue

        fill = find_fill(
            rows,
            index + 1,
            trade["side"],
            float(trade["contracts"]),
            "dual_stop",
        )
        if fill:
            fill["latency_seconds"] = round(
                (
                    parse_tick_time(fill["ts"])
                    - when
                ).total_seconds(),
                3,
            )

        terminal = str(
            trade.get("result") or ""
        ).lower()
        terminal_known = terminal in ("yes", "no")
        recovered = (
            terminal == trade["side"]
            if terminal_known
            else None
        )

        hold_pnl = None
        if terminal_known:
            payout = (
                float(trade["contracts"])
                if recovered
                else 0.0
            )
            hold_pnl = round(
                payout - float(trade["cost_usd"]),
                2,
            )

        stop_pnl = None
        if fill:
            stop_pnl = round(
                float(trade["contracts"])
                * fill["price"]
                - taker_fee(
                    fill["price"],
                    float(trade["contracts"]),
                )
                - float(trade["cost_usd"]),
                2,
            )

        return {
            "status": "eligible",
            "signal_ts": row["ts"],
            "signal_bid": held_bid,
            "proxy_implied_spot": round(implied, 8),
            "proxy_distance_pct": round(
                state["proxy_distance_pct"], 8
            ),
            "regime": state["regime"],
            "proximity_threshold_pct":
                state["proximity_threshold_pct"],
            "terminal_known": terminal_known,
            "recovered_at_settlement": recovered,
            "hold_to_settlement_pnl_usd": hold_pnl,
            "counterfactual_stop_pnl_usd": stop_pnl,
            "hold_minus_stop_usd": (
                None
                if hold_pnl is None or stop_pnl is None
                else round(hold_pnl - stop_pnl, 2)
            ),
            "stop_fill": fill,
            "missing_proxy_candidates_before_event":
                missing_proxy_candidates,
        }

    return {
        "status": (
            "unresolved_proxy"
            if missing_proxy_candidates
            else "not_eligible"
        ),
        "missing_proxy_candidates":
            missing_proxy_candidates,
    }


def simulate_trade(
    trade: dict,
    meta: dict,
    rows: list[dict],
    store: TickStore,
) -> dict:
    target, target_source = target_for_trade(trade)
    visited_cells: set[str] = set()
    first_cell = None
    last_cell = None
    proxy_failures = 0
    unfilled_signal = None

    for index, row in enumerate(rows):
        when = row["_dt"]
        tau_seconds = (
            meta["close_utc"] - when
        ).total_seconds()
        if tau_seconds <= 0:
            break

        held_bid, _ = side_quote(row, trade["side"])
        if held_bid is None:
            continue

        timing = (
            "late"
            if tau_seconds <= LATE_SECONDS
            else "early"
        )
        implied = store.implied_spot(
            when.date(),
            meta["cluster_key"],
            row["ts"],
        )

        state = None
        if implied is not None:
            state = classify_cell(
                when,
                meta["close_utc"],
                implied,
                meta["strike"],
                trade["side"],
            )
            visited_cells.add(state["cell"])
            first_cell = first_cell or state["cell"]
            last_cell = state["cell"]
        else:
            proxy_failures += 1

        action = None

        # Existing double-condition stop remains prior to the profit leg:
        # bid trigger AND spot losing/inside the registered proximity band.
        if held_bid < BID_TRIGGER:
            if state is None:
                return {
                    "status": "SKIP",
                    "skip_reason":
                        "proxy_unavailable_at_stop_decision",
                    "proxy_failures": proxy_failures,
                    "visited_cells": sorted(visited_cells),
                }
            if state["losing"] or state["near"]:
                action = "dual_stop"

        if action is None and timing == "late":
            if state is None:
                return {
                    "status": "SKIP",
                    "skip_reason":
                        "proxy_unavailable_in_late_window",
                    "proxy_failures": proxy_failures,
                    "visited_cells": sorted(visited_cells),
                }
            if state["near"]:
                action = "late_near_lock"
            # late+far cancels the capture target and holds.

        elif (
            action is None
            and timing == "early"
            and target is not None
            and held_bid >= target
        ):
            action = "early_capture"

        if action is None:
            continue

        fill = find_fill(
            rows,
            index + 1,
            trade["side"],
            float(trade["contracts"]),
            action,
        )
        if fill is None:
            unfilled_signal = {
                "action": action,
                "ts": row["ts"],
                "bid": held_bid,
            }
            break

        fill["latency_seconds"] = round(
            (
                parse_tick_time(fill["ts"])
                - when
            ).total_seconds(),
            3,
        )
        exit_fee = taker_fee(
            fill["price"],
            float(trade["contracts"]),
        )
        policy_pnl = round(
            float(trade["contracts"])
            * fill["price"]
            - exit_fee
            - float(trade["cost_usd"]),
            2,
        )

        return {
            "status": "REPLAYED",
            "policy_action": action,
            "signal_ts": row["ts"],
            "policy_realized_ts": fill["ts"],
            "policy_exit_price": fill["price"],
            "policy_exit_fee_usd": exit_fee,
            "policy_pnl_usd": policy_pnl,
            "target_price": target,
            "target_source": target_source,
            "entry_cell": first_cell,
            "exit_cell": (
                state["cell"]
                if state
                else f"{timing}_unknown"
            ),
            "visited_cells": sorted(visited_cells),
            "proxy_failures": proxy_failures,
            "fill_assumptions": fill,
        }

    terminal = str(trade.get("result") or "").lower()
    if terminal not in ("yes", "no"):
        return {
            "status": "SKIP",
            "skip_reason":
                "terminal_outcome_unavailable_for_policy_hold",
            "target_price": target,
            "target_source": target_source,
            "entry_cell": first_cell,
            "visited_cells": sorted(visited_cells),
            "proxy_failures": proxy_failures,
            "unfilled_signal": unfilled_signal,
        }

    won = terminal == trade["side"]
    payout = (
        float(trade["contracts"])
        if won
        else 0.0
    )
    policy_pnl = round(
        payout - float(trade["cost_usd"]),
        2,
    )

    return {
        "status": "REPLAYED",
        "policy_action": "hold_to_settlement",
        "signal_ts": None,
        "policy_realized_ts":
            iso_utc(meta["close_utc"]),
        "policy_exit_price": 1.0 if won else 0.0,
        "policy_exit_fee_usd": 0.0,
        "policy_pnl_usd": policy_pnl,
        "target_price": target,
        "target_source": target_source,
        "entry_cell": first_cell,
        "exit_cell": last_cell,
        "visited_cells": sorted(visited_cells),
        "proxy_failures": proxy_failures,
        "unfilled_signal": unfilled_signal,
    }


def full_loss(pnl: float, cost: float) -> bool:
    return pnl <= -0.80 * cost + 1e-12


def max_drawdown(
    events: list[tuple[dt.datetime, int, float]],
) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0

    for _, _, pnl in sorted(
        events,
        key=lambda event: (event[0], event[1]),
    ):
        equity += pnl
        peak = max(peak, equity)
        worst = max(worst, peak - equity)

    return round(worst, 2)


def percentile(
    sorted_values: list[float],
    probability: float,
) -> float:
    if not sorted_values:
        raise ValueError("empty percentile")

    index = (len(sorted_values) - 1) * probability
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return sorted_values[lower]

    weight = index - lower
    return (
        sorted_values[lower] * (1.0 - weight)
        + sorted_values[upper] * weight
    )


def cluster_bootstrap_ci(
    rows: list[dict],
) -> tuple[list[float] | None, int]:
    cluster_sums: dict[str, float] = (
        collections.defaultdict(float)
    )
    for row in rows:
        cluster_sums[row["cluster_key"]] += (
            row["ev_diff_usd"]
        )

    values = list(cluster_sums.values())
    if not values:
        return None, 0

    rng = random.Random(BOOTSTRAP_SEED)
    cluster_count = len(values)
    draws = []

    for _ in range(BOOTSTRAP_REPS):
        draws.append(
            sum(
                values[rng.randrange(cluster_count)]
                for _ in range(cluster_count)
            )
        )

    draws.sort()
    return [
        round(percentile(draws, 0.025), 4),
        round(percentile(draws, 0.975), 4),
    ], cluster_count


def md_escape(value) -> str:
    if value is None:
        return "—"
    return (
        str(value)
        .replace("|", r"\|")
        .replace("\n", " ")
    )


def fmt_money(value) -> str:
    if value is None:
        return "—"
    return f"${float(value):+.2f}"


def build_markdown(report: dict) -> str:
    coverage = report["coverage"]
    aggregate = report["aggregate"]
    open_cell = report["open_cell"]

    lines = [
        "# τ-出场预注册回测",
        "",
        (
            f"**有效配对样本 n={coverage['replayed_n']} / "
            f"ledger 候选 {coverage['ledger_candidate_n']}；"
            f"SKIP={coverage['skipped_n']}；"
            f"独立窗口簇={aggregate['cluster_n']}。**"
        ),
        "",
        (
            f"机械裁决：**{report['decision']['overall']}**。"
            "样本与跳过数是裁决的一部分；"
            "不向缺档日期或不适用产品外推。"
        ),
        "",
        "## 判据",
        "",
        "| 预注册判据 | 观测值 | PASS/FAIL |",
        "|---|---:|:---:|",
    ]

    for criterion in report["criteria"]:
        lines.append(
            f"| {md_escape(criterion['criterion'])} | "
            f"{md_escape(criterion['observed'])} | "
            f"{criterion['status']} |"
        )

    lines += [
        "",
        "## 配对聚合",
        "",
        "| 指标 | baseline 实际 | τ×贴线政策 | 差值 |",
        "|---|---:|---:|---:|",
        (
            f"| 总 P&L | "
            f"{fmt_money(aggregate['baseline_total_pnl_usd'])} | "
            f"{fmt_money(aggregate['policy_total_pnl_usd'])} | "
            f"{fmt_money(aggregate['total_ev_diff_usd'])} |"
        ),
        (
            "| 满损笔数（亏损≥80%成本） | "
            f"{aggregate['baseline_full_loss_n']} | "
            f"{aggregate['policy_full_loss_n']} | "
            f"{aggregate['policy_full_loss_n'] - aggregate['baseline_full_loss_n']:+d} |"
        ),
        (
            "| 最大已实现权益回撤 | "
            f"{fmt_money(aggregate['baseline_max_drawdown_usd'])} | "
            f"{fmt_money(aggregate['policy_max_drawdown_usd'])} | "
            f"{fmt_money(aggregate['policy_max_drawdown_usd'] - aggregate['baseline_max_drawdown_usd'])} |"
        ),
        "",
        (
            "总 EV 差采用按市场窗口簇配对 bootstrap"
            f"（{BOOTSTRAP_REPS:,} 次，seed={BOOTSTRAP_SEED}）；"
            f"95% CI：{aggregate['ev_diff_bootstrap_ci95_usd']}。"
        ),
        "",
        "## 预注册开放格子：早期+贴线若扛到结算",
        "",
    ]

    if open_cell["eligible_n"]:
        lines.append(
            f"条件恢复率：**{open_cell['recovered_n']}/"
            f"{open_cell['eligible_n']} = "
            f"{open_cell['recovery_rate']:.1%}**"
            "（恢复定义：持仓侧最终结算为赢）。"
        )
    else:
        lines.append(
            "条件恢复率：**NA"
            "（0 个可判定的早期+贴线双条件仓位）**。"
        )

    lines += [
        (
            "代理缺失而无法归类的仓位："
            f"{open_cell['unresolved_proxy_n']}；"
            f"终局未知：{open_cell['terminal_unknown_n']}。"
        ),
        "",
        "## 2×2 政策（冻结）",
        "",
        "| τ | 报价隐含贴线代理 | 动作 |",
        "|---|---|---|",
        (
            "| 早期（τ>W/3） | 贴线 | "
            "保留 0.6-capture；双条件止损照旧 |"
        ),
        (
            "| 早期（τ>W/3） | 远离 | "
            "保留 0.6-capture；亏损侧穿越仍受双条件止损 |"
        ),
        (
            "| 晚期（τ≤W/3） | 贴线 | "
            "下一 tick 全 taker 锁定 |"
        ),
        (
            "| 晚期（τ≤W/3） | 远离 | "
            "撤 capture 目标，持有到结算；双条件止损仍优先 |"
        ),
        "",
        "## 覆盖与跳过",
        "",
        (
            "可见 tick 日期："
            f"{', '.join(coverage['tick_days_available']) or '无'}。"
        ),
        (
            "实际只读打开日期："
            f"{', '.join(coverage['tick_days_opened']) or '无'}。"
        ),
        "",
        "| SKIP 原因 | 笔数 |",
        "|---|---:|",
    ]

    for reason, count in sorted(
        coverage["skip_reasons"].items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(
            f"| {md_escape(reason)} | {count} |"
        )

    lines += [
        "",
        "## 逐仓对照",
        "",
        (
            "| id | ticker | side | baseline P&L | policy P&L | "
            "EV差 | policy动作/格子 | 状态或SKIP原因 |"
        ),
        "|---:|---|:---:|---:|---:|---:|---|---|",
    ]

    for row in report["positions"]:
        if row["status"] == "REPLAYED":
            action = (
                f"{row.get('policy_action')} / "
                f"{row.get('exit_cell') or row.get('entry_cell') or 'unknown'}"
            )
            status = "REPLAYED"
        else:
            action = "—"
            status = row.get("skip_reason", "unknown")

        lines.append(
            f"| {row['id']} | {md_escape(row['ticker'])} | "
            f"{row['side']} | "
            f"{fmt_money(row.get('baseline_pnl_usd'))} | "
            f"{fmt_money(row.get('policy_pnl_usd'))} | "
            f"{fmt_money(row.get('ev_diff_usd'))} | "
            f"{md_escape(action)} | {md_escape(status)} |"
        )

    lines += [
        "",
        "## 假设与局限",
        "",
    ]
    for limitation in report["limitations"]:
        lines.append(f"- {limitation}")

    lines += [
        "",
        "## 只读与 schema 审计",
        "",
        (
            "- ledger URI：`mode=ro`；trades 列："
            f"{', '.join(report['schema']['ledger_columns'])}。"
        ),
        (
            "- tick 数据库均以 `mode=ro` 打开；"
            "仅在沙箱无法取得历史文件共享锁时追加 "
            "`immutable=1`，并在 JSON 的 `open_modes` 留痕。"
        ),
        (
            "- 配置冻结值核对："
            f"{'全部一致' if report['config_audit']['all_match'] else '存在漂移，见 JSON'}。"
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preregistered τ-exit tick replay "
            "(read-only inputs)."
        )
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help=(
            "Directory for tau_exit_backtest.json "
            "and tau_exit_backtest.md"
        ),
    )
    args = parser.parse_args()

    for path in (
        SPEC_PATH,
        CONFIG_PATH,
        LEDGER_PATH,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not TICK_DIR.is_dir():
        raise FileNotFoundError(TICK_DIR)

    spec_bytes = SPEC_PATH.read_bytes()
    config_audit = audit_config()

    ledger, ledger_open_mode = connect_readonly(
        LEDGER_PATH
    )
    required_ledger_columns = {
        "id",
        "ts",
        "mode",
        "ticker",
        "title",
        "side",
        "price",
        "contracts",
        "cost_usd",
        "fee_usd",
        "status",
        "result",
        "pnl_usd",
        "settled_ts",
        "exit_type",
        "target_price",
        "stop_price",
        "exit_price",
        "booked_ts",
        "q_consensus",
    }
    ledger_columns = table_columns(ledger, "trades")
    missing_ledger_columns = sorted(
        required_ledger_columns - set(ledger_columns)
    )
    if missing_ledger_columns:
        ledger.close()
        raise RuntimeError(
            "ledger trades schema missing: "
            f"{missing_ledger_columns}"
        )

    trades = [
        dict(row)
        for row in ledger.execute(
            "SELECT * FROM trades "
            "WHERE mode='live' "
            "AND status IN ('settled','closed') "
            "AND ts>=? "
            "ORDER BY ts,id",
            (START_TS,),
        )
    ]
    ledger.close()

    tick_file_count = len(
        list(TICK_DIR.glob("ticks_*.db"))
    )
    print(
        f"[start] ledger candidates={len(trades)}; "
        f"tick files discovered={tick_file_count}"
    )

    store = TickStore(TICK_DIR)
    positions = []
    skip_counts = collections.Counter()
    recovery_rows = []

    for number, trade in enumerate(trades, 1):
        ticker = str(trade.get("ticker") or "")
        side = str(trade.get("side") or "").lower()
        series = (
            ticker.split("-", 1)[0]
            if "-" in ticker
            else ticker
        )

        position = {
            "id": int(trade["id"]),
            "ts": trade.get("ts"),
            "booked_ts": trade.get("booked_ts"),
            "ticker": ticker,
            "title": trade.get("title"),
            "side": side,
            "contracts": trade.get("contracts"),
            "cost_usd": trade.get("cost_usd"),
            "baseline_status": trade.get("status"),
            "baseline_result": trade.get("result"),
            "baseline_exit_price":
                trade.get("exit_price"),
            "baseline_realized_ts":
                trade.get("settled_ts"),
            "baseline_pnl_usd": trade.get("pnl_usd"),
            "status": "SKIP",
        }

        reason = None
        if series not in SUPPORTED_SERIES:
            reason = "unsupported_policy_scope"

        meta = (
            parse_contract(ticker)
            if reason is None
            else None
        )
        if reason is None and meta is None:
            reason = (
                "unsupported_or_unparseable_"
                "hourly_strike_contract"
            )

        if reason is None and side not in ("yes", "no"):
            reason = "invalid_side"

        try:
            contracts = float(trade["contracts"])
            cost = float(trade["cost_usd"])
            baseline_pnl = float(trade["pnl_usd"])
            entry_price = float(trade["price"])
            if not (
                contracts > 0
                and cost > 0
                and 0 < entry_price < 1
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            if reason is None:
                reason = (
                    "invalid_position_economics_"
                    "or_baseline_pnl"
                )

        entry_utc = None
        if reason is None:
            entry_utc = parse_ledger_time(
                trade.get("booked_ts")
                or trade.get("ts")
            )
            if (
                entry_utc is None
                or entry_utc >= meta["close_utc"]
            ):
                reason = (
                    "entry_time_missing_"
                    "or_not_before_close"
                )

        path = None
        coverage = None
        if reason is None:
            try:
                path, coverage = store.load_path(
                    ticker,
                    entry_utc,
                    meta["close_utc"],
                )
                if path is not None:
                    store.prepare_no_index_proxy_range(
                        meta["cluster_key"],
                        entry_utc,
                        meta["close_utc"],
                    )
            except (
                FileNotFoundError,
                RuntimeError,
                sqlite3.Error,
            ) as error:
                coverage = {
                    "reason": "tick_database_error",
                    "detail": (
                        f"{type(error).__name__}: {error}"
                    ),
                }
                path = None

            position["coverage"] = coverage
            if path is None:
                reason = coverage.get(
                    "reason",
                    "tick_path_unavailable",
                )

        if reason is None:
            position.update({
                "series": meta["series"],
                "strike": meta["strike"],
                "close_utc":
                    iso_utc(meta["close_utc"]),
                "entry_utc": iso_utc(entry_utc),
                "cluster_key": meta["cluster_key"],
            })

            open_cell = detect_open_cell(
                trade,
                meta,
                path,
                store,
            )
            position["open_cell"] = open_cell
            if open_cell["status"] in (
                "eligible",
                "unresolved_proxy",
            ):
                recovery_rows.append({
                    "id": position["id"],
                    "ticker": ticker,
                    **open_cell,
                })

            simulated = simulate_trade(
                trade,
                meta,
                path,
                store,
            )
            position.update(simulated)

            if simulated["status"] == "REPLAYED":
                position["baseline_pnl_usd"] = round(
                    baseline_pnl, 2
                )
                position["policy_pnl_usd"] = round(
                    float(simulated["policy_pnl_usd"]),
                    2,
                )
                position["ev_diff_usd"] = round(
                    position["policy_pnl_usd"]
                    - position["baseline_pnl_usd"],
                    2,
                )

                baseline_time = (
                    parse_ledger_time(
                        trade.get("settled_ts")
                    )
                    or meta["close_utc"]
                )
                position["baseline_realized_utc"] = (
                    iso_utc(baseline_time)
                )
                position["baseline_full_loss"] = (
                    full_loss(
                        position["baseline_pnl_usd"],
                        cost,
                    )
                )
                position["policy_full_loss"] = (
                    full_loss(
                        position["policy_pnl_usd"],
                        cost,
                    )
                )
            else:
                reason = simulated.get(
                    "skip_reason",
                    "policy_replay_failed",
                )

        if reason is not None:
            position["status"] = "SKIP"
            position["skip_reason"] = reason
            skip_counts[reason] += 1

        positions.append(position)

        if number % 50 == 0:
            replayed_so_far = sum(
                row["status"] == "REPLAYED"
                for row in positions
            )
            print(
                f"[progress] {number}/{len(trades)}; "
                f"replayed={replayed_so_far}; "
                f"skipped={number - replayed_so_far}"
            )

    paired = [
        row
        for row in positions
        if row["status"] == "REPLAYED"
    ]

    baseline_events = [
        (
            parse_tick_time(
                row["baseline_realized_utc"]
            ),
            row["id"],
            row["baseline_pnl_usd"],
        )
        for row in paired
    ]
    policy_events = [
        (
            parse_tick_time(
                row["policy_realized_ts"]
            ),
            row["id"],
            row["policy_pnl_usd"],
        )
        for row in paired
    ]

    bootstrap_ci, cluster_count = (
        cluster_bootstrap_ci(paired)
    )
    baseline_full_loss_count = sum(
        row["baseline_full_loss"] for row in paired
    )
    policy_full_loss_count = sum(
        row["policy_full_loss"] for row in paired
    )
    baseline_drawdown = max_drawdown(
        baseline_events
    )
    policy_drawdown = max_drawdown(
        policy_events
    )
    baseline_total = round(
        sum(
            row["baseline_pnl_usd"]
            for row in paired
        ),
        2,
    )
    policy_total = round(
        sum(
            row["policy_pnl_usd"]
            for row in paired
        ),
        2,
    )
    total_difference = round(
        sum(row["ev_diff_usd"] for row in paired),
        2,
    )

    criteria = [
        {
            "criterion":
                "满损笔数（亏损≥80%成本）下降",
            "observed": (
                f"baseline={baseline_full_loss_count}, "
                f"policy={policy_full_loss_count}"
            ),
            "status": (
                "PASS"
                if (
                    paired
                    and policy_full_loss_count
                    < baseline_full_loss_count
                )
                else "FAIL"
            ),
        },
        {
            "criterion": "最大回撤下降",
            "observed": (
                f"baseline=${baseline_drawdown:.2f}, "
                f"policy=${policy_drawdown:.2f}"
            ),
            "status": (
                "PASS"
                if (
                    paired
                    and policy_drawdown
                    < baseline_drawdown
                )
                else "FAIL"
            ),
        },
        {
            "criterion":
                "总 EV 差 bootstrap 95% CI 不显著为负",
            "observed": (
                (
                    f"Δ=${total_difference:+.2f}, "
                    f"CI=[${bootstrap_ci[0]:+.4f}, "
                    f"${bootstrap_ci[1]:+.4f}]"
                )
                if bootstrap_ci
                else "NA（无有效配对样本）"
            ),
            # Not significantly negative means the whole CI
            # is not below zero.
            "status": (
                "PASS"
                if (
                    bootstrap_ci is not None
                    and bootstrap_ci[1] >= 0
                )
                else "FAIL"
            ),
        },
    ]
    overall = (
        "PASS"
        if all(
            item["status"] == "PASS"
            for item in criteria
        )
        else "FAIL"
    )

    eligible_recovery = [
        row
        for row in recovery_rows
        if (
            row["status"] == "eligible"
            and row.get("terminal_known")
        )
    ]
    recovered_count = sum(
        bool(row.get("recovered_at_settlement"))
        for row in eligible_recovery
    )
    unresolved_proxy_count = sum(
        row["status"] == "unresolved_proxy"
        for row in recovery_rows
    )
    terminal_unknown_count = sum(
        (
            row["status"] == "eligible"
            and not row.get("terminal_known")
        )
        for row in recovery_rows
    )

    cells_observed = {
        cell: {
            "visited_positions": 0,
            "exit_positions": 0,
        }
        for cell in (
            "early_near",
            "early_far",
            "late_near",
            "late_far",
        )
    }
    for row in paired:
        for cell in row.get("visited_cells", []):
            if cell in cells_observed:
                cells_observed[cell][
                    "visited_positions"
                ] += 1
        exit_cell = row.get("exit_cell")
        if exit_cell in cells_observed:
            cells_observed[exit_cell][
                "exit_positions"
            ] += 1

    limitations = [
        (
            "tick schema contains Kalshi order-book quotes only; "
            "it has no Coinbase/CF index spot, strike metadata "
            "table, or 24h realized-volatility series."
        ),
        (
            "The script infers a spot proxy as the ladder strike "
            "where contemporaneous YES probability crosses 0.5. "
            "This quote-implied median is endogenous to Kalshi "
            "and cannot reproduce the registered unmanipulable "
            "spot confirmation."
        ),
        (
            "Because 24h composite RV is unavailable, non-macro "
            "observations use production's blind-data fallback "
            "`elevated` (0.075%); registered macro windows use "
            "`storm` (0.10%). Calm/storm RV thresholds remain "
            "frozen but cannot be observed."
        ),
        (
            "15-minute crypto contracts are skipped: their "
            "reference is the prior window's published settlement, "
            "which is absent from tick DBs. Weather and event "
            "contracts are outside this hourly crypto τ policy."
        ),
        (
            "Naive ledger timestamps are interpreted using US "
            "Mountain time; ticker close codes use US Eastern "
            "wall time. Standard US DST rules convert both to UTC."
        ),
        (
            "Execution is conservative: signal on one snapshot, "
            "fill no earlier than the next snapshot, require full "
            "displayed top-of-book depth, charge the general taker "
            "fee, and subtract an extra 2c on dual-stop fills. "
            "Hidden depth, queue priority, partial fills, and "
            "favorable improvement are ignored."
        ),
        (
            "Maximum drawdown uses chronological realized P&L on "
            "the paired subset, not unavailable intratrade "
            "portfolio mark-to-market. Total EV difference is the "
            "paired realized-P&L difference."
        ),
        (
            "A position is skipped for a missing day, empty ticker "
            "path, a boundary/internal gap above five times "
            "empirical median cadence (at least 5s), an unavailable "
            "proxy at a policy decision, or an unknown terminal "
            "result when policy holds."
        ),
    ]

    aggregate = {
        "paired_n": len(paired),
        "cluster_n": cluster_count,
        "baseline_total_pnl_usd": baseline_total,
        "policy_total_pnl_usd": policy_total,
        "total_ev_diff_usd": total_difference,
        "ev_diff_bootstrap_ci95_usd": bootstrap_ci,
        "bootstrap_reps": BOOTSTRAP_REPS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_unit": "ticker window cluster",
        "baseline_full_loss_n":
            baseline_full_loss_count,
        "policy_full_loss_n":
            policy_full_loss_count,
        "baseline_max_drawdown_usd":
            baseline_drawdown,
        "policy_max_drawdown_usd":
            policy_drawdown,
    }

    policy_scope_count = sum(
        parse_contract(
            str(trade.get("ticker") or "")
        ) is not None
        for trade in trades
    )
    valid_candidate_pnl = []
    for trade in trades:
        try:
            valid_candidate_pnl.append(
                float(trade["pnl_usd"])
            )
        except (KeyError, TypeError, ValueError):
            pass

    report = {
        "metadata": {
            "generated_at_utc": iso_utc(
                dt.datetime.now(UTC),
                timespec="seconds",
            ),
            "spec_path": str(SPEC_PATH),
            "spec_sha256": hashlib.sha256(
                spec_bytes
            ).hexdigest(),
            "config_path": str(CONFIG_PATH),
            "ledger_path": str(LEDGER_PATH),
            "tick_dir": str(TICK_DIR),
            "input_database_open_mode":
                "SQLite URI mode=ro",
            "ledger_open_mode": ledger_open_mode,
            "spot_available": False,
            "spot_proxy":
                "Kalshi ladder 0.5-probability strike",
            "ledger_timezone":
                "America/Denver with US DST rules",
            "market_ticker_timezone":
                "America/New_York with US DST rules",
        },
        "frozen_parameters": {
            "late_rule": "tau <= window/3",
            "window_seconds": WINDOW_SECONDS,
            "late_seconds": LATE_SECONDS,
            "bid_trigger_strict_less_than":
                BID_TRIGGER,
            "proximity_pct_by_regime":
                PROXIMITY_PCT,
            "regime_calm_max": REGIME_CALM_MAX,
            "regime_storm_min": REGIME_STORM_MIN,
            "take_profit_capture":
                TAKE_PROFIT_CAPTURE,
            "min_target_move": MIN_TARGET_MOVE,
            "stop_exit_cross": EXIT_CROSS,
        },
        "config_audit": config_audit,
        "schema": {
            "ledger_columns": ledger_columns,
            "tick_by_day": store.schema_audit,
            "query_plans": store.query_plans,
            "open_modes": store.open_modes,
        },
        "coverage": {
            "ledger_candidate_n": len(trades),
            "policy_scope_hourly_crypto_n":
                policy_scope_count,
            "replayed_n": len(paired),
            "skipped_n": len(trades) - len(paired),
            "skip_reasons": dict(skip_counts),
            "tick_days_available": [
                day.isoformat()
                for day in sorted(store.files)
            ],
            "tick_days_opened":
                sorted(store.open_modes),
            "all_candidate_baseline_pnl_usd":
                round(sum(valid_candidate_pnl), 2),
            "comparison_subset":
                "replayed paired positions only",
        },
        "policy_cells_observed": cells_observed,
        "positions": positions,
        "aggregate": aggregate,
        "open_cell": {
            "definition": (
                "first early+near observation with held-side "
                "bid < 0.70; recovery means held side wins "
                "at settlement"
            ),
            "eligible_n": len(eligible_recovery),
            "recovered_n": recovered_count,
            "recovery_rate": (
                recovered_count / len(eligible_recovery)
                if eligible_recovery
                else None
            ),
            "unresolved_proxy_n":
                unresolved_proxy_count,
            "terminal_unknown_n":
                terminal_unknown_count,
            "positions": recovery_rows,
        },
        "criteria": criteria,
        "decision": {
            "overall": overall,
            "rule": (
                "PASS only if all three "
                "preregistered criteria PASS"
            ),
            "underpowered_warning":
                len(paired) < 100,
        },
        "limitations": limitations,
        "warnings": sorted(store.warnings),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    json_path = (
        args.out / "tau_exit_backtest.json"
    )
    markdown_path = (
        args.out / "tau_exit_backtest.md"
    )

    json_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    markdown_path.write_text(
        build_markdown(report),
        encoding="utf-8",
    )

    store.close()

    print(
        f"[done] replayed={len(paired)} "
        f"skipped={len(trades) - len(paired)} "
        f"overall={overall}"
    )
    print(f"[wrote] {json_path}")
    print(f"[wrote] {markdown_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
