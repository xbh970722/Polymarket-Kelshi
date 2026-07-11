"""Weather lane CALIBRATION track (paper, D-class, read-only).

The weather taker lane shows +$3.17 realized but on n=21 with 92% of P&L from 3
trades -- statistically indistinguishable from luck (same thin-n trap the maker
council rejected). Before anyone scales it (a user-exclusive lever, frozen till
07-23), we must learn whether the NWS model actually has an edge. This tool
accumulates that proof at zero incremental risk:

  backfill   import the model's already-TRADED weather predictions from the live
             ledger (q_consensus vs realized settlement) for an immediate read.
  record     run the live weather model (src.weather.candidates) and log EVERY
             open-bucket prediction vs the market mid -- including untraded ones,
             which is where the real calibration sample lives. Run daily in the
             active window; dedups on ticker+date.
  score      fetch settlements for unresolved rows, compute model-Brier vs
             market-Brier. The model only earns a size-up case if its Brier beats
             the market over n>=50 with the fee-adjusted edge CI lower bound > 0.

Outside the trading path by design: no order code, only public settlement reads.
Brier(p) = (p - outcome)^2, lower is better.
"""
import argparse
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.kalshi_client import KalshiPublic  # noqa: E402

LEDGER = Path("data") / "weather_calibration.jsonl"
LIVE_DB = Path("data") / "ledger.db"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(ln) for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _save(rows: list[dict]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _key(r: dict) -> tuple:
    return (r.get("ticker"), (r.get("recorded_ts") or "")[:10], r.get("source"))


def cmd_backfill(_args) -> None:
    """Seed from already-traded weather predictions in the live ledger."""
    if not LIVE_DB.exists():
        print("backfill: no ledger.db")
        return
    c = sqlite3.connect(LIVE_DB); c.row_factory = sqlite3.Row
    rows = _load()
    have = {_key(r) for r in rows}
    added = 0
    q = ("SELECT ticker, ts, q_consensus, market_prob, result, side, rationale "
         "FROM trades WHERE mode='live' AND (rationale LIKE 'NWS%' OR rationale LIKE 'W2 fade%')")
    for r in c.execute(q):
        outcome = None
        if (r["result"] or "").lower() in ("yes", "no"):
            outcome = 1.0 if r["result"].lower() == "yes" else 0.0
        # BUGFIX (codex-verify 2026-07-11): q_consensus/market_prob are stored in
        # the FILLED SIDE's convention; a NO-side fill records P(NO). Convert to a
        # consistent YES-convention before Brier, or NO-side rows score the wrong
        # probability against the YES outcome (inflated model Brier, false "no edge").
        q_side, m_side = r["q_consensus"], r["market_prob"]
        yes_flip = (r["side"] == "no")
        q_yes = None if q_side is None else (1.0 - q_side if yes_flip else q_side)
        m_yes = None if m_side is None else (1.0 - m_side if yes_flip else m_side)
        row = {"ticker": r["ticker"], "source": "ledger-traded",
               "recorded_ts": r["ts"], "q_model": q_yes,
               "market_mid": m_yes, "side": r["side"],
               "lane": "W1" if (r["rationale"] or "").startswith("NWS") else "W2",
               "outcome": outcome, "result": (r["result"] or None), "resolved_ts": None}
        if _key(row) in have:
            continue
        rows.append(row); added += 1
    _save(rows)
    print(f"backfill: +{added} traded weather rows, ledger now {len(rows)} total")


def cmd_record(_args) -> None:
    """Log today's live weather-model predictions (traded or not)."""
    from src import weather
    from src.pipeline import load_config
    cfg = load_config()
    try:
        cands = weather.candidates(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"record: weather.candidates failed ({e})")
        return
    if not cands:
        print("record: 0 candidates (outside active local hours [11,21], or no NWS data). "
              "Run during the daytime window to accumulate.")
        return
    rows = _load()
    have = {_key(r) for r in rows}
    now = _now_iso(); added = 0
    for cd in cands:
        row = {"ticker": cd["ticker"], "source": "model-live", "recorded_ts": now,
               "q_model": cd["q_model"], "market_mid": cd["mid"],
               "yes_ask": cd.get("yes_ask"), "lane": "W1", "series": cd.get("series"),
               "mu": cd.get("mu"), "sigma": cd.get("sigma"), "local_hour": cd.get("local_hour"),
               "outcome": None, "result": None, "resolved_ts": None}
        if _key(row) in have:
            continue
        rows.append(row); added += 1
    _save(rows)
    print(f"record: +{added} live model predictions, ledger now {len(rows)} total")


def _brier(p, o):
    return None if p is None else round((p - o) ** 2, 4)


def cmd_score(_args) -> None:
    rows = _load()
    if not rows:
        print("score: empty; run `backfill` and/or `record` first")
        return
    api = KalshiPublic(); newly = 0
    for r in rows:
        if r.get("outcome") is not None:
            continue
        try:
            m = api._get(f"/markets/{r['ticker']}").get("market", {})
        except Exception:  # noqa: BLE001
            continue
        res = (m.get("result") or "").lower()
        if res in ("yes", "no"):
            r["outcome"] = 1.0 if res == "yes" else 0.0
            r["result"] = res; r["resolved_ts"] = _now_iso(); newly += 1
    if newly:
        _save(rows)
    resolved = [r for r in rows if r.get("outcome") is not None and r.get("q_model") is not None]
    pending = [r for r in rows if r.get("outcome") is None]
    print("=== WEATHER MODEL CALIBRATION (paper, D-class, read-only) ===")
    print(f"resolved={len(resolved)}  pending={len(pending)}  (+{newly} newly)")
    if resolved:
        mb = [_brier(r["q_model"], r["outcome"]) for r in resolved]
        kb = [_brier(r["market_mid"], r["outcome"]) for r in resolved if r.get("market_mid") is not None]
        model = round(sum(mb) / len(mb), 4)
        market = round(sum(kb) / len(kb), 4) if kb else None
        print(f"\nBrier (lower=better)  model={model}  market={market}  naive0.5=0.25")
        if market is not None:
            better = "MODEL beats market" if model < market else "market beats model"
            print(f"  -> {better} over n={len(kb)}  (need model<market on n>=50 to justify size-up)")
    if pending:
        print(f"\npending: {len(pending)} awaiting settlement")
    print("\nprint!=fill; D-class; scaling weather size is a user-exclusive lever (frozen till 07-23).")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="weather_calibration")
    sub = ap.add_subparsers(required=True)
    sub.add_parser("backfill").set_defaults(fn=cmd_backfill)
    sub.add_parser("record").set_defaults(fn=cmd_record)
    sub.add_parser("score").set_defaults(fn=cmd_score)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
