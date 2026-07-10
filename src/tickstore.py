r"""Read-only tick consumption layer (D3-CRYPTO-STRUCTURAL, build_d3_spec §2).

FREEZE-14 research-only infrastructure. This module NEVER writes to the tick
partitions and NEVER imports pipeline/live/order-capable code. Every SQLite
connection is opened `file:...?mode=ro` with `PRAGMA query_only=ON`; every hot
query is bound by ticker + a finite time window (single day partition ~55M rows
— an unbounded scan is an incident). immutable=1 is banned (would miss WAL on a
live partition).

Data reality (measured, frozen — spec §2.1):
  partition  D:\kalshi-ticks\ticks_YYYYMMDD.db  (UTC-date named)
  table      book(ts TEXT, ticker TEXT, yes_bid REAL, yes_ask REAL,
                  bid_sz REAL, ask_sz REAL, l2_json TEXT, l3_json TEXT,
                  last_trade_px REAL, seq INTEGER)   index (ticker, ts)
  ts is a uniform 24-char 'YYYY-MM-DDTHH:MM:SS.mmmZ' UTC string ⇒ lexical order
  == time order ⇒ TEXT BETWEEN rides the index. l2_json=top-2, l3_json=top-3
  {"bid":[[px,sz],..],"ask":[..]}; a lean row (top-of-book only) has both NULL
  ⇒ carry-forward semantics. seq is provenance only (adjacent values jump);
  continuity is judged purely on timestamps.

Price unit (spec §2.2 / manifest F2): price_mills = floor(db_real*1000 + 0.5),
integer thousandths of a dollar (860 mills == 86c, 1c == 10 mills). If
abs(db_real*1000 - mills) > 1e-6 the row carries quality flag
PRICE_SCALE_RESIDUAL and must not enter any touch/through/fill decision. size is
a finite non-negative float.
"""
import datetime as dt
import glob
import json
import math
import os
import re
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass

Mills = int       # thousandths of a dollar: 860 == 86c
MS = int          # epoch milliseconds, UTC

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
_DAY_RE = re.compile(r"ticks_(\d{8})\.db$", re.IGNORECASE)
_REQUIRED_COLS = ("ts", "ticker", "yes_bid", "yes_ask", "bid_sz", "ask_sz",
                  "l2_json", "l3_json", "last_trade_px", "seq")
_RESIDUAL_TOL = 1e-6


# --------------------------------------------------------------------------- #
# time helpers (integer-exact; no float epoch drift)
# --------------------------------------------------------------------------- #
def iso_to_ms(ts: str) -> MS:
    """'YYYY-MM-DDTHH:MM:SS.mmmZ' -> epoch ms. Falls back to a lenient parse."""
    try:
        d = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=dt.timezone.utc)
    except ValueError:
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
    delta = d - _EPOCH
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


def ms_to_iso(ms: MS) -> str:
    """epoch ms -> canonical 24-char 'YYYY-MM-DDTHH:MM:SS.mmmZ'."""
    d = _EPOCH + dt.timedelta(milliseconds=ms)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _day_of_ms(ms: MS) -> str:
    d = _EPOCH + dt.timedelta(milliseconds=ms)
    return d.strftime("%Y%m%d")


def _to_mills(db_real) -> tuple[Mills | None, bool]:
    """(price_mills, residual_ok). residual_ok False -> PRICE_SCALE_RESIDUAL."""
    if db_real is None:
        return None, True
    x = float(db_real) * 1000.0
    m = math.floor(x + 0.5)
    return m, abs(x - m) <= _RESIDUAL_TOL


def _to_size(x) -> float | None:
    if x is None:
        return None
    v = float(x)
    if not math.isfinite(v):
        return None
    return v if v >= 0.0 else 0.0


# --------------------------------------------------------------------------- #
# value types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BookLevel:
    price_mills: Mills
    size: float


@dataclass(frozen=True)
class Book:
    ticker: str
    ts_ms: MS
    seq: int | None
    yes_bid_mills: Mills | None
    yes_ask_mills: Mills | None
    bid_sz: float | None
    ask_sz: float | None
    bid_levels: tuple[BookLevel, ...] | None   # None = lean row carried no l2/l3
    ask_levels: tuple[BookLevel, ...] | None
    last_trade_mills: Mills | None
    quality: frozenset[str]                    # {"PRICE_SCALE_RESIDUAL","BAD_JSON"}
    src_db: str


@dataclass(frozen=True)
class Coverage:
    rows: int
    first_ms: MS | None
    last_ms: MS | None
    max_gap_ms: int          # rows==0 -> full window length; edges included
    complete: bool           # max_gap_ms <= gap_threshold_ms


@dataclass(frozen=True)
class DwellResult:
    dwell_ms: int
    complete: bool
    max_gap_ms: int
    rows: int


class Unobserved:
    """Sentinel: a depth query landed on a price the top-3 snapshot never
    carried. This is NOT size 0 — absence of observation, not observed absence."""
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self) -> str:      # pragma: no cover - cosmetic
        return "UNOBSERVED"

    def __bool__(self) -> bool:
        return False


UNOBSERVED = Unobserved()


class TickstoreSchemaError(Exception):
    """Raised when a partition's book table is missing a required column."""


# --------------------------------------------------------------------------- #
# row -> Book
# --------------------------------------------------------------------------- #
def _parse_levels(raw: str | None) -> tuple[tuple[BookLevel, ...] | None,
                                            tuple[BookLevel, ...] | None, bool, bool]:
    """(bid_levels, ask_levels, ok_json, residual_ok). raw None -> (None,None) lean."""
    if raw is None:
        return None, None, True, True
    try:
        obj = json.loads(raw)
        residual_ok = True

        def _side(key: str) -> tuple[BookLevel, ...]:
            nonlocal residual_ok
            out = []
            for px, sz in obj.get(key, []):
                m, rok = _to_mills(px)
                s = _to_size(sz)
                if m is None or s is None:
                    residual_ok = False
                    continue
                residual_ok = residual_ok and rok
                out.append(BookLevel(m, s))
            return tuple(out)

        return _side("bid"), _side("ask"), True, residual_ok
    except (ValueError, TypeError, KeyError):
        return None, None, False, True


def _row_to_book(row: sqlite3.Row, src_db: str) -> Book:
    yb, yb_ok = _to_mills(row["yes_bid"])
    ya, ya_ok = _to_mills(row["yes_ask"])
    ltp, ltp_ok = _to_mills(row["last_trade_px"])
    bid_levels, ask_levels, ok_json, lvl_res_ok = _parse_levels(row["l3_json"]
                                                                if row["l3_json"] is not None
                                                                else row["l2_json"])
    flags: set[str] = set()
    if not (yb_ok and ya_ok and ltp_ok and lvl_res_ok):
        flags.add("PRICE_SCALE_RESIDUAL")
    if not ok_json:
        flags.add("BAD_JSON")
    return Book(
        ticker=row["ticker"],
        ts_ms=iso_to_ms(row["ts"]),
        seq=row["seq"],
        yes_bid_mills=yb,
        yes_ask_mills=ya,
        bid_sz=_to_size(row["bid_sz"]),
        ask_sz=_to_size(row["ask_sz"]),
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        last_trade_mills=ltp,
        quality=frozenset(flags),
        src_db=src_db,
    )


def depth_at(book: Book, side: str, price_mills: Mills) -> float | Unobserved:
    """Size resting at price_mills on `side` ('bid'|'ask'). Missing level (or a
    lean row that carried no depth) -> UNOBSERVED, never 0 (spec §2.3)."""
    if side == "bid":
        levels = book.bid_levels
    elif side == "ask":
        levels = book.ask_levels
    else:
        raise ValueError(f"side must be 'bid'|'ask', got {side!r}")
    if levels is None:
        return UNOBSERVED
    for lv in levels:
        if lv.price_mills == price_mills:
            return lv.size
    return UNOBSERVED


# --------------------------------------------------------------------------- #
# TickStore
# --------------------------------------------------------------------------- #
class TickStore:
    def __init__(self, root: str = r"D:\kalshi-ticks",
                 pattern: str = "ticks_*.db") -> None:
        self.root = root
        self.pattern = pattern
        self._conns: dict[str, sqlite3.Connection] = {}
        self._validated: set[str] = set()

    # ---- discovery -------------------------------------------------------- #
    def days(self) -> list[str]:
        out = []
        for p in glob.glob(os.path.join(self.root, self.pattern)):
            m = _DAY_RE.search(os.path.basename(p))
            if m:
                out.append(m.group(1))
        return sorted(set(out))

    def _path(self, day: str) -> str:
        return os.path.join(self.root, f"ticks_{day}.db")

    def _open(self, day: str) -> sqlite3.Connection | None:
        c = self._conns.get(day)
        if c is not None:
            return c
        path = self._path(day)
        if not os.path.exists(path):
            return None
        uri = f"file:{path.replace(os.sep, '/')}?mode=ro"   # read-only, no immutable
        c = sqlite3.connect(uri, uri=True, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA query_only=ON")
        self._validate(c, day)
        self._conns[day] = c
        return c

    def _validate(self, c: sqlite3.Connection, day: str) -> None:
        if day in self._validated:
            return
        cols = {r["name"] for r in c.execute("PRAGMA table_info(book)")}
        if not cols:
            raise TickstoreSchemaError(f"{day}: no 'book' table")
        missing = [col for col in _REQUIRED_COLS if col not in cols]
        if missing:
            raise TickstoreSchemaError(f"{day}: book missing columns {missing}")
        self._validated.add(day)

    def close(self) -> None:
        for c in self._conns.values():
            try:
                c.close()
            except sqlite3.Error:
                pass
        self._conns.clear()

    def tickers(self, day: str, like: str | None = None) -> list[str]:
        """Distinct tickers in a partition. `like` is a GLOB prefix (rides the
        (ticker, ts) index). Discovery helper — the only non-ticker-bound query."""
        c = self._open(day)
        if c is None:
            return []
        if like:
            rows = c.execute(
                "SELECT DISTINCT ticker FROM book WHERE ticker GLOB ? ORDER BY ticker",
                (like,))
        else:
            rows = c.execute("SELECT DISTINCT ticker FROM book ORDER BY ticker")
        return [r["ticker"] for r in rows]

    # ---- partition span for a time window --------------------------------- #
    def _span_days(self, start_ms: MS, end_ms: MS) -> list[str]:
        d0 = _EPOCH + dt.timedelta(milliseconds=start_ms)
        d1 = _EPOCH + dt.timedelta(milliseconds=end_ms)
        out, cur = [], dt.datetime(d0.year, d0.month, d0.day, tzinfo=dt.timezone.utc)
        last = dt.datetime(d1.year, d1.month, d1.day, tzinfo=dt.timezone.utc)
        while cur <= last:
            out.append(cur.strftime("%Y%m%d"))
            cur += dt.timedelta(days=1)
        return out            # 1..3 partitions for our windows (cross-midnight is normal)

    # ---- iteration -------------------------------------------------------- #
    def iter_books(self, ticker: str, start_ms: MS, end_ms: MS,
                   *, carry_l2: bool = False) -> Iterator[Book]:
        """Yield Books for ticker in [start_ms, end_ms] in time order, stitching
        adjacent UTC-day partitions (20:00 ET close == 00:00 UTC next day, so a
        window routinely straddles two partitions). Each partition is queried on
        its own disjoint ts sub-range so cross-partition ordering is exact and no
        row is double-counted. carry_l2=True forward-fills a lean row's levels
        from the most recent row that carried depth."""
        last_bid: tuple[BookLevel, ...] | None = None
        last_ask: tuple[BookLevel, ...] | None = None
        prev_key: tuple[MS, int | None] | None = None
        for day in self._span_days(start_ms, end_ms):
            c = self._open(day)
            if c is None:
                continue
            day_lo = iso_to_ms(f"{day[:4]}-{day[4:6]}-{day[6:]}T00:00:00.000Z")
            day_hi = day_lo + 86_400_000 - 1
            lo, hi = max(start_ms, day_lo), min(end_ms, day_hi)
            if lo > hi:
                continue
            rows = c.execute(
                "SELECT ts,ticker,yes_bid,yes_ask,bid_sz,ask_sz,l2_json,l3_json,"
                "last_trade_px,seq FROM book WHERE ticker=? AND ts BETWEEN ? AND ? "
                "ORDER BY ts",
                (ticker, ms_to_iso(lo), ms_to_iso(hi)))
            for row in rows:
                b = _row_to_book(row, day)
                key = (b.ts_ms, b.seq)
                if key == prev_key:                 # conservative de-dup (ticker,ts,seq)
                    continue
                prev_key = key
                if carry_l2:
                    if b.bid_levels is None and b.ask_levels is None:
                        if last_bid is not None or last_ask is not None:
                            b = Book(b.ticker, b.ts_ms, b.seq, b.yes_bid_mills,
                                     b.yes_ask_mills, b.bid_sz, b.ask_sz,
                                     last_bid, last_ask, b.last_trade_mills,
                                     b.quality | {"CARRIED_L2"}, b.src_db)
                    else:
                        last_bid, last_ask = b.bid_levels, b.ask_levels
                yield b

    def book_at(self, ticker: str, ts_ms: MS,
                *, max_age_ms: int = 120_000) -> Book | None:
        """Last book at-or-before ts_ms within max_age_ms, else None (stale==absent)."""
        lo = ts_ms - max_age_ms
        best: Book | None = None
        for day in self._span_days(lo, ts_ms):
            c = self._open(day)
            if c is None:
                continue
            row = c.execute(
                "SELECT ts,ticker,yes_bid,yes_ask,bid_sz,ask_sz,l2_json,l3_json,"
                "last_trade_px,seq FROM book WHERE ticker=? AND ts BETWEEN ? AND ? "
                "ORDER BY ts DESC LIMIT 1",
                (ticker, ms_to_iso(lo), ms_to_iso(ts_ms))).fetchone()
            if row is not None:
                b = _row_to_book(row, day)
                if best is None or b.ts_ms > best.ts_ms:
                    best = b
        return best

    def latest_book(self, ticker: str,
                    *, max_age_ms: int | None = None) -> Book | None:
        """Newest book for ticker across partitions (search newest day backward).
        max_age_ms compares against wall-clock now (historical rows read stale)."""
        for day in reversed(self.days()):
            c = self._open(day)
            if c is None:
                continue
            row = c.execute(
                "SELECT ts,ticker,yes_bid,yes_ask,bid_sz,ask_sz,l2_json,l3_json,"
                "last_trade_px,seq FROM book WHERE ticker=? ORDER BY ts DESC LIMIT 1",
                (ticker,)).fetchone()
            if row is not None:
                b = _row_to_book(row, day)
                if max_age_ms is not None:
                    now_ms = int((dt.datetime.now(dt.timezone.utc) - _EPOCH)
                                 .total_seconds() * 1000)
                    if now_ms - b.ts_ms > max_age_ms:
                        return None
                return b
        return None

    # ---- coverage / dwell ------------------------------------------------- #
    def _ts_series(self, ticker: str, start_ms: MS, end_ms: MS) -> list[MS]:
        out: list[MS] = []
        prev: MS | None = None
        for day in self._span_days(start_ms, end_ms):
            c = self._open(day)
            if c is None:
                continue
            day_lo = iso_to_ms(f"{day[:4]}-{day[4:6]}-{day[6:]}T00:00:00.000Z")
            day_hi = day_lo + 86_400_000 - 1
            lo, hi = max(start_ms, day_lo), min(end_ms, day_hi)
            if lo > hi:
                continue
            for r in c.execute(
                    "SELECT ts FROM book WHERE ticker=? AND ts BETWEEN ? AND ? "
                    "ORDER BY ts", (ticker, ms_to_iso(lo), ms_to_iso(hi))):
                m = iso_to_ms(r["ts"])
                if m == prev:
                    continue
                prev = m
                out.append(m)
        return out

    def coverage(self, ticker: str, start_ms: MS, end_ms: MS,
                 *, gap_threshold_ms: int = 120_000) -> Coverage:
        """Row count + max inter-quote gap over [start,end], EDGES INCLUDED
        (start->first and last->end count as gaps). rows==0 -> gap = window len."""
        ts = self._ts_series(ticker, start_ms, end_ms)
        if not ts:
            span = max(0, end_ms - start_ms)
            return Coverage(0, None, None, span, span <= gap_threshold_ms)
        max_gap = max(ts[0] - start_ms, end_ms - ts[-1])
        for a, b in zip(ts, ts[1:]):
            max_gap = max(max_gap, b - a)
        return Coverage(len(ts), ts[0], ts[-1], max_gap, max_gap <= gap_threshold_ms)

    def dwell_ms(self, ticker: str, end_ms: MS,
                 predicate: Callable[[Book], bool],
                 *, max_lookback_ms: int,
                 max_gap_ms: int = 120_000) -> DwellResult:
        """Contiguous span (ending at-or-before end_ms) over which predicate has
        held without an inter-quote gap > max_gap_ms, looking back at most
        max_lookback_ms. complete=False if the last book fails predicate or the
        run was cut by an oversized gap (an incomplete dwell must not pass a gate)."""
        books = list(self.iter_books(ticker, end_ms - max_lookback_ms, end_ms))
        if not books:
            return DwellResult(0, False, 0, 0)
        i = len(books) - 1
        if not predicate(books[i]):
            return DwellResult(0, False, 0, 0)
        included = [books[i]]
        prev_ts = books[i].ts_ms
        max_gap = 0
        complete = True
        j = i - 1
        while j >= 0:
            gap = prev_ts - books[j].ts_ms
            if gap > max_gap_ms:
                complete = False            # cut by a gap -> dwell not contiguous
                break
            if not predicate(books[j]):
                break                       # clean start (predicate boundary)
            included.append(books[j])
            max_gap = max(max_gap, gap)
            prev_ts = books[j].ts_ms
            j -= 1
        span = included[0].ts_ms - included[-1].ts_ms
        return DwellResult(span, complete, max_gap, len(included))
