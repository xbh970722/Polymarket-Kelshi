"""Events lane BLIND-CALIBRATION scorer (paper, D-class, read-only).

The pre-registered promotion gate in events-report counts *paper trades*; a
research batch that finds no edge (all no_trade) trades nothing and therefore
accumulates zero evidence there. But the honest question option (a) wants
answered -- "is the blind 4-model ensemble EVER trustworthy?" -- does not need a
trade. It needs the blind consensus scored against the realized YES/NO once each
market resolves, and compared to the market price that was live at estimate time.

This tool is deliberately OUTSIDE src/events.py (the money-path red-line module):
it never imports live/ledger, never places an order, only reads Kalshi public
settlement. Two modes:

  record  --research F --snapshot G   append a batch's blind estimates + the
                                      market mid that was live at estimate time
                                      to data/events_calibration.jsonl (idempotent
                                      on research_run_id+ticker).
  score                               fetch resolutions for any unresolved rows,
                                      persist outcomes, print ensemble-vs-market
                                      Brier over the resolved set.

Brier(p) = (p - outcome)^2, lower is better. The ensemble only earns trust if
its mean Brier beats the market's over a meaningful resolved sample (n>=20).
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.kalshi_client import KalshiPublic  # noqa: E402

LEDGER = Path("data") / "events_calibration.jsonl"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load() -> list[dict]:
    if not LEDGER.exists():
        return []
    rows = []
    for ln in LEDGER.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            rows.append(json.loads(ln))
    return rows


def _save(rows: list[dict]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                      encoding="utf-8")


def cmd_record(args) -> None:
    doc = json.loads(Path(args.research).read_text(encoding="utf-8"))
    snap = json.loads(Path(args.snapshot).read_text(encoding="utf-8")) if args.snapshot else {}
    run_id = doc.get("research_run_id")
    rows = _load()
    have = {(r.get("research_run_id"), r.get("ticker")) for r in rows}
    added = 0
    for it in doc.get("items", []):
        tk = it.get("ticker")
        if (run_id, tk) in have:
            continue
        ps = [e["p_yes"] for e in it.get("estimators", []) if e.get("p_yes") is not None]
        if not ps:
            continue
        cons = round(sum(ps) / len(ps), 4)
        cis = [e.get("ci80") for e in it.get("estimators", []) if e.get("ci80")]
        ci_w = round(sum(c[1] - c[0] for c in cis) / len(cis), 4) if cis else None
        s = snap.get(tk, {})
        yb, ya = s.get("yes_bid"), s.get("yes_ask")
        mid = round((yb + ya) / 2.0, 4) if (yb is not None and ya is not None) else None
        rows.append({
            "research_run_id": run_id, "ticker": tk,
            "consensus": cons, "opus_mean": it.get("q_claude"),
            "codex_mean": it.get("q_codex"), "ci_width": ci_w,
            "market_mid": mid, "market_yes_ask": ya,
            "close_time": it.get("close_time"),
            "recommended_action": it.get("recommended_action"),
            "estimate_ts": it.get("asof") or _now_iso(),
            "outcome": None, "result": None, "resolved_ts": None,
        })
        added += 1
    _save(rows)
    print(f"record: +{added} row(s), ledger now {len(rows)} total ({LEDGER})")


def _brier(p, outcome):
    return None if p is None else round((p - outcome) ** 2, 4)


def cmd_score(args) -> None:
    rows = _load()
    if not rows:
        print("score: ledger empty; run `record` first")
        return
    api = KalshiPublic()
    newly = 0
    for r in rows:
        if r.get("outcome") is not None:
            continue
        try:
            m = api._get(f"/markets/{r['ticker']}").get("market", {})
        except Exception as e:  # noqa: BLE001
            print(f"  WARN {r['ticker']}: fetch failed ({e})")
            continue
        res = (m.get("result") or "").lower()
        if res in ("yes", "no"):
            r["outcome"] = 1.0 if res == "yes" else 0.0
            r["result"] = res
            r["resolved_ts"] = _now_iso()
            newly += 1
    if newly:
        _save(rows)

    resolved = [r for r in rows if r.get("outcome") is not None]
    pending = [r for r in rows if r.get("outcome") is None]

    print(f"=== EVENTS BLIND-CALIBRATION (paper, D-class, read-only) ===")
    print(f"resolved={len(resolved)}  pending={len(pending)}  (+{newly} newly this run)")
    if resolved:
        eb = [(_brier(r["consensus"], r["outcome"])) for r in resolved]
        mb = [(_brier(r["market_mid"], r["outcome"])) for r in resolved if r["market_mid"] is not None]
        ens = round(sum(eb) / len(eb), 4)
        mkt = round(sum(mb) / len(mb), 4) if mb else None
        print(f"\nBrier (lower=better)  ensemble={ens}  market={mkt}  naive0.5=0.25")
        if mkt is not None:
            verdict = "ENSEMBLE beats market" if ens < mkt else "market beats ensemble"
            print(f"  -> {verdict} by {abs(ens-(mkt or 0)):.4f} over n={len(mb)}")
        print(f"\n{'ticker':34s} {'cons':>5s} {'mkt':>5s} {'out':>4s} {'ensB':>6s} {'mktB':>6s}")
        for r in sorted(resolved, key=lambda x: x["ticker"]):
            print(f"{r['ticker'][:34]:34s} {r['consensus']:.2f} "
                  f"{('  -' if r['market_mid'] is None else format(r['market_mid'],'.2f')):>5s} "
                  f"{r['outcome']:>4.0f} {str(_brier(r['consensus'],r['outcome'])):>6s} "
                  f"{str(_brier(r['market_mid'],r['outcome']) if r['market_mid'] is not None else '-'):>6s}")
    if pending:
        print(f"\npending (awaiting resolution):")
        for r in sorted(pending, key=lambda x: x.get("close_time") or ""):
            print(f"  {r['ticker'][:40]:40s} cons={r['consensus']:.2f} "
                  f"mkt={('-' if r['market_mid'] is None else format(r['market_mid'],'.2f'))} "
                  f"close={r.get('close_time')}")
    print("\nprint!=fill; D-class mechanism evidence, never feeds the live edge gate.")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="events_calibration")
    sub = ap.add_subparsers(required=True)
    pr = sub.add_parser("record")
    pr.add_argument("--research", required=True)
    pr.add_argument("--snapshot", default=None)
    pr.set_defaults(fn=cmd_record)
    ps = sub.add_parser("score")
    ps.set_defaults(fn=cmd_score)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
