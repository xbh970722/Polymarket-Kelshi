r"""H16 quote-shadow replay CLI (build_d3_spec §4.1).

FREEZE-14 research-only. No order path exists here — this only reads tick
partitions (read-only), acquires Coinbase public candles, records the quote
shadow into data/h16_shadow.db, fetches official Kalshi settlements, and reports
gate lines. Nothing places, sizes, or enables anything.

  python scripts/h16_shadow_replay.py candles  [--days N | --range A,B]
  python scripts/h16_shadow_replay.py backfill [--days 20260708,20260709]
  python scripts/h16_shadow_replay.py backfill --since-last
  python scripts/h16_shadow_replay.py settle   [--limit 100] [--rps 1.0]
  python scripts/h16_shadow_replay.py report   [--all-partitions]

backfill auto-runs the candle acquisition phase first (fail-closed semantics
unchanged); backfill and --since-last share one code path (同码原则).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import h16shadow as h16  # noqa: E402
from src.kalshi_client import KalshiPublic  # noqa: E402
from src.tickstore import TickStore, iso_to_ms  # noqa: E402

PRODUCTS = list(h16.PRODUCT.values())
GRANS = (300, 60)                       # 5m (spot/reference) + 1m (rv_1h)


def _day_bounds_ms(days: list[str]) -> tuple[int, int]:
    starts = [iso_to_ms(f"{d[:4]}-{d[4:6]}-{d[6:]}T00:00:00.000Z") for d in days]
    lo = min(starts) - 3 * 3_600_000        # 3h margin for rv_1h + reference lookback
    hi = max(starts) + 86_400_000 + 600_000  # day end + 10m
    return lo, hi


def _resolve_days(store: TickStore, days_arg: str | None,
                  since_last: bool, n: int | None,
                  rng: str | None) -> list[str]:
    avail = store.days()
    if since_last:
        last = h16.last_backfilled_day()
        return [d for d in avail if last is None or d > last]
    if days_arg:
        want = [d.strip() for d in days_arg.split(",") if d.strip()]
        return [d for d in avail if d in want] or want
    if rng:
        a, b = (x.strip() for x in rng.split(","))
        return [d for d in avail if a <= d <= b]
    if n:
        return avail[-n:]
    return avail


def cmd_candles(store: TickStore, days: list[str]) -> int:
    if not days:
        print("candles: no days resolved"); return 0
    lo, hi = _day_bounds_ms(days)
    total = 0
    for g in GRANS:
        got = h16.fetch_candles(PRODUCTS, g, lo, hi)
        print(f"candles g={g}s: upserted {got} rows over {len(days)} day(s)")
        total += got
    h16.log_run("candles", days, notes=f"gran={GRANS} rows={total}")
    return total


def cmd_backfill(store: TickStore, days: list[str]) -> None:
    if not days:
        print("backfill: no days resolved (nothing new)"); return
    print(f"backfill days: {days}")
    cmd_candles(store, days)                 # acquisition phase first (fail-closed)
    made = 0
    for day in days:
        for family in h16.MANIFEST_V2["families"]:
            made += h16.detect_windows(store, day, family)
    print(f"detect: {made} new intents")
    ev = h16.evaluate_all(store)
    print(f"evaluate: {ev} intents replayed")
    oc = h16.compute_outcomes()
    print(f"outcomes: {oc} arm rows")
    h16.log_run("backfill", days, notes=f"intents={made} eval={ev} outcomes={oc}")


def cmd_settle(limit: int, rps: float) -> None:
    n = h16.fetch_settlements(KalshiPublic(), limit=limit, rps=rps)
    oc = h16.compute_outcomes()
    print(f"settle: {n} official settlements; outcomes recomputed ({oc} rows)")
    h16.log_run("settle", notes=f"settled={n} limit={limit} rps={rps}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="H16 quote-shadow replay (FREEZE-14 research-only, zero orders).",
        epilog="FREEZE-14: shadow/infra only. No live/probe/enable switch exists. "
               "quote-proxy fills are an UPPER BOUND, never confirmed maker fills.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("candles", help="Coinbase public candle acquisition")
    p.add_argument("--days", type=int, default=None, help="last N available days")
    p.add_argument("--range", dest="rng", default=None, help="A,B (YYYYMMDD,YYYYMMDD)")

    p = sub.add_parser("backfill", help="candles + detect + evaluate + outcomes")
    p.add_argument("--days", dest="days", default=None, help="comma list YYYYMMDD")
    p.add_argument("--since-last", action="store_true", help="days after last backfill")

    p = sub.add_parser("settle", help="official Kalshi settlement fetch (<=1 rps)")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--rps", type=float, default=1.0)

    p = sub.add_parser("report", help="gate ledger (official partition by default)")
    p.add_argument("--all-partitions", action="store_true",
                   help="include unsettled/proxy windows (diagnostic, not gate-eligible)")

    args = ap.parse_args()
    store = TickStore(root=r"D:\kalshi-ticks")
    try:
        if args.cmd == "candles":
            days = _resolve_days(store, None, False, args.days, args.rng)
            cmd_candles(store, days)
        elif args.cmd == "backfill":
            days = _resolve_days(store, args.days, args.since_last, None, None)
            cmd_backfill(store, days)
        elif args.cmd == "settle":
            cmd_settle(args.limit, args.rps)
        elif args.cmd == "report":
            print(h16.report(official_only=not args.all_partitions))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
