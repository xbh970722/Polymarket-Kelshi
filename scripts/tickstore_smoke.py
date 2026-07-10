r"""Read-only smoke for src/tickstore.py (build_d3_spec §4.2).

FREEZE-14 research-only. Opens one day partition read-only, asserts schema v1 +
24-char ts, exercises iter_books/book_at/coverage/dwell_ms/depth_at on a few
tickers, prints row counts / timing / a quality histogram. Zero writes: the
mode=ro contract is asserted two ways (uri substring + a write that must fail).

  python scripts/tickstore_smoke.py --db D:\kalshi-ticks\ticks_20260708.db
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tickstore import (  # noqa: E402
    UNOBSERVED, Book, TickStore, TickstoreSchemaError, depth_at, iso_to_ms,
)


def _assert_read_only(path: str) -> None:
    uri = f"file:{path.replace(os.sep, '/')}?mode=ro"
    assert "mode=ro" in uri, "connection string must be mode=ro"
    c = sqlite3.connect(uri, uri=True)
    c.execute("PRAGMA query_only=ON")
    wrote = False
    try:
        c.execute("CREATE TABLE _smoke_should_fail(x)")
        wrote = True
    except sqlite3.OperationalError:
        pass
    finally:
        c.close()
    assert not wrote, "read-only connection accepted a write — ABORT"
    print(f"  read-only asserted: uri has mode=ro + write rejected")


def _pick_tickers(store: TickStore, day: str, n: int = 3) -> list[str]:
    for like in ("KXBTC15M-*", "KXBTCD-*", "KX*"):
        ts = store.tickers(day, like=like)
        if ts:
            return ts[:n]
    return store.tickers(day)[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description="tickstore read-only smoke (FREEZE-14).")
    ap.add_argument("--db", required=True, help=r"path to ticks_YYYYMMDD.db")
    args = ap.parse_args()

    path = args.db
    if not os.path.exists(path):
        print(f"ERROR: no such db: {path}")
        return 2
    root = os.path.dirname(path) or "."
    base = os.path.basename(path)
    day = base.replace("ticks_", "").replace(".db", "")
    print(f"tickstore smoke: {base} (day={day}, root={root})")

    _assert_read_only(path)

    store = TickStore(root=root, pattern="ticks_*.db")
    try:
        # schema detection (raises TickstoreSchemaError on unknown schema)
        try:
            tickers_probe = store.tickers(day, like="KXBTC15M-*")
        except TickstoreSchemaError as e:
            print(f"  SCHEMA ERROR: {e}")
            return 3
        print(f"  schema v1 OK; sample KXBTC15M tickers: {len(tickers_probe)}")

        day_lo = iso_to_ms(f"{day[:4]}-{day[4:6]}-{day[6:]}T00:00:00.000Z")
        day_hi = day_lo + 86_400_000 - 1

        picks = _pick_tickers(store, day)
        if not picks:
            print("  no tickers in partition — nothing to exercise")
            return 0
        print(f"  exercising {len(picks)} tickers: {picks}")

        qual: Counter = Counter()
        ts_len_bad = 0
        total_rows = 0
        for tk in picks:
            t0 = time.perf_counter()
            books: list[Book] = list(store.iter_books(tk, day_lo, day_hi))
            dt_ms = (time.perf_counter() - t0) * 1000
            total_rows += len(books)
            for b in books:
                for f in b.quality:
                    qual[f] += 1
            # ts is 24-char per spec — verify on the raw first row
            c = store._open(day)
            raw = c.execute("SELECT ts FROM book WHERE ticker=? ORDER BY ts LIMIT 1",
                            (tk,)).fetchone()
            if raw and len(raw["ts"]) != 24:
                ts_len_bad += 1

            if not books:
                print(f"    {tk}: 0 rows")
                continue
            first, last = books[0].ts_ms, books[-1].ts_ms
            mid = (first + last) // 2

            ba = store.book_at(tk, mid, max_age_ms=120_000)
            cov = store.coverage(tk, first, last)
            # anchor dwell at the last two-sided book so the span is meaningful
            populated = [b.ts_ms for b in books if b.yes_ask_mills is not None]
            dwell_end = populated[-1] if populated else last
            dw = store.dwell_ms(tk, dwell_end, lambda b: b.yes_ask_mills is not None,
                                max_lookback_ms=10_000, max_gap_ms=2_000)

            # depth_at: a real level round-trips to its size; a bogus price -> UNOBSERVED
            depth_hit = depth_at(books[-1], "ask", books[-1].yes_ask_mills) \
                if books[-1].yes_ask_mills is not None else UNOBSERVED
            depth_miss = depth_at(books[-1], "bid", -12345)
            assert depth_miss is UNOBSERVED, "missing level must be UNOBSERVED, not 0"

            print(f"    {tk}: rows={len(books)} span={(last-first)/1000:.1f}s "
                  f"iter={dt_ms:.0f}ms book_at={'hit' if ba else 'none'} "
                  f"cov(rows={cov.rows},max_gap={cov.max_gap_ms}ms,complete={cov.complete}) "
                  f"dwell(ms={dw.dwell_ms},rows={dw.rows},complete={dw.complete}) "
                  f"depth_ask={'UNOBS' if depth_hit is UNOBSERVED else 'obs'}")

        print(f"  totals: rows={total_rows} ts_len!=24: {ts_len_bad}")
        print(f"  quality histogram: {dict(qual) if qual else '{} (clean)'}")
        assert ts_len_bad == 0, "found ts not 24 chars"
        print("SMOKE OK (zero writes).")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
