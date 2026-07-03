"""Pipeline CLI.

    python -m src.pipeline scan                       # scan markets -> data/candidates.json
    python -m src.pipeline rules TICKER               # print full rules + quotes for one market
    python -m src.pipeline decide --research FILE     # apply engine+risk to research JSON, record paper orders
    python -m src.pipeline settle                     # settle any resolved open positions
    python -m src.pipeline report                     # write reports/report_<date>.md
    python -m src.pipeline status                     # one-line ledger status

The research step (intel gathering + dual-model debate) happens in Claude Code,
following research/PROTOCOL.md. This CLI only does the deterministic parts.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import yaml

from . import engine, ledger
from .kalshi_client import KalshiPublic
from .scanner import scan

REPORTS = Path("reports")


def load_config() -> dict:
    return yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))


def live_active(cfg: dict) -> bool:
    """Live orders flow only when BOTH switches are on; keys are checked at placement."""
    return cfg["mode"] == "live" and bool(cfg.get("live", {}).get("enabled"))


def cmd_scan(_args) -> None:
    cfg = load_config()
    rows = scan(cfg)
    data = json.loads((Path("data") / "candidates.json").read_text(encoding="utf-8"))
    print("categories seen:", json.dumps(data["categories_seen"]))
    print(f"shortlist ({len(rows)}):")
    for r in rows:
        print(f"  {r['score']:6.3f}  {r['ticker']:<42} mid={r['mid_prob']:5.2f} "
              f"v24h={r['volume_24h']:<9.0f} oi={r['open_interest']:<9.0f} "
              f"d2c={r['days_to_close']:>5.1f}  {(r['title'] + ' | ' + r['subtitle'])[:70]}")


def cmd_rules(args) -> None:
    api = KalshiPublic()
    m = api.market(args.ticker)
    keys = ("ticker", "title", "yes_sub_title", "rules_primary", "rules_secondary",
            "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars",
            "last_price_dollars", "volume_24h_fp", "open_interest_fp",
            "close_time", "expected_expiration_time", "status")
    print(json.dumps({k: m.get(k) for k in keys}, indent=2, ensure_ascii=False))


def cmd_decide(args) -> None:
    cfg = load_config()
    is_live = live_active(cfg)
    if is_live:
        # live mode tightens the per-trade cap to min(risk, live)
        cfg["risk"]["max_per_trade_usd"] = min(cfg["risk"]["max_per_trade_usd"],
                                               cfg["live"]["max_per_trade_usd"])
    research = json.loads(Path(args.research).read_text(encoding="utf-8"))
    api = KalshiPublic()
    placed = skipped = 0
    for item in research["items"]:
        ticker = item["ticker"]
        if ledger.has_open_position(ticker):
            print(f"SKIP  {ticker}: already holding an open position")
            skipped += 1
            continue
        mn = api.market_norm(ticker)
        ya, na, yb = mn["yes_ask"], mn["no_ask"], mn["yes_bid"]
        if not (0.01 <= ya <= 0.99 and 0.01 <= na <= 0.99):
            print(f"SKIP  {ticker}: no live two-sided quote")
            skipped += 1
            continue
        d = engine.decide(item["q_claude"], item["q_codex"], ya, na, cfg)
        if d.action == "skip":
            print(f"SKIP  {ticker}: {d.reason}")
            skipped += 1
            continue
        veto = engine.check_risk(ledger.stats(), d.cost_usd, cfg)
        if veto:
            print(f"VETO  {ticker}: {veto}")
            skipped += 1
            continue
        market_prob = round((yb + ya) / 2, 4) if yb else round(ya, 4)
        status = "pending" if is_live else "open"
        ledger.insert_trade(
            mode=cfg["mode"], ticker=ticker, title=item.get("title", ""),
            side=d.side, price=d.price, contracts=d.contracts,
            cost_usd=d.cost_usd, fee_usd=d.fee_usd,
            q_claude=item["q_claude"], q_codex=item["q_codex"],
            q_consensus=d.q_consensus, market_prob=market_prob,
            edge_net=d.edge_net, rationale=item.get("rationale", ""),
            status=status)
        placed += 1
        tag = "LIVE-PENDING" if is_live else "PAPER"
        print(f"{tag} {ticker}: {d.side.upper()} x{d.contracts} @ {d.price * 100:.1f}c "
              f"cost=${d.cost_usd:.2f} (fee ${d.fee_usd:.2f}) edge={d.edge_net:+.3f} "
              f"q={d.q_consensus:.2f} vs mkt={market_prob:.2f}")
    if is_live and placed:
        print(f"NOTE: {placed} live order(s) are PENDING confirmation. "
              f"Review with 'pending', then 'execute-live --confirmed'.")
    print(f"done: {placed} orders ({'live-pending' if is_live else 'paper'}), {skipped} skipped")


def cmd_settle(_args) -> None:
    api = KalshiPublic()
    settled = 0
    for t in ledger.open_trades():
        try:
            m = api.market(t["ticker"])
        except Exception as e:
            print(f"WARN  {t['ticker']}: fetch failed ({e})")
            continue
        if m.get("status") in ("settled", "finalized") and m.get("result") in ("yes", "no"):
            win = m["result"] == t["side"]
            pnl = round(t["contracts"] - t["cost_usd"], 2) if win else round(-t["cost_usd"], 2)
            ledger.settle_trade(t["id"], m["result"], pnl)
            settled += 1
            print(f"SETTLED {t['ticker']}: result={m['result']} "
                  f"{'WIN' if win else 'LOSS'} pnl=${pnl:+.2f}")
    print(f"done: {settled} settled, {len(ledger.open_trades())} still open")


def cmd_report(_args) -> None:
    cfg = load_config()
    api = KalshiPublic()
    st, cal = ledger.stats(), ledger.calibration()
    today = dt.date.today().isoformat()
    lines = [f"# Paper Trading Report - {today}", "",
             f"mode: **{cfg['mode']}** | bankroll: ${cfg['sizing']['bankroll_usd']} | "
             f"1/{int(1 / cfg['sizing']['kelly_fraction'])} Kelly", "",
             "## Open positions", ""]
    opens = ledger.open_trades()
    if not opens:
        lines.append("_none_")
    else:
        lines += ["| ticker | side | qty | entry | mark | unreal P&L | model q | net edge |",
                  "|---|---|---|---|---|---|---|---|"]
        unreal_total = 0.0
        for t in opens:
            try:
                mn = api.market_norm(t["ticker"])
                yb, ya = mn["yes_bid"], mn["yes_ask"]
                mark_yes = (yb + ya) / 2 if (yb and ya) else mn["last_price"]
            except Exception:
                mark_yes = None
            if mark_yes is None:
                mark_s, unreal = "?", 0.0
            else:
                mark = mark_yes if t["side"] == "yes" else 1 - mark_yes
                unreal = t["contracts"] * mark - t["cost_usd"]
                mark_s = f"{mark:.2f}"
            unreal_total += unreal
            lines.append(f"| {t['ticker']} | {t['side']} | {t['contracts']} | "
                         f"{t['price'] * 100:.1f}c | {mark_s} | {unreal:+.2f} | "
                         f"{t['q_consensus']:.2f} | {t['edge_net']:+.3f} |")
        lines += ["", f"unrealized total: **{unreal_total:+.2f} USD**"]
    r = cfg["risk"]
    lines += ["", "## Risk usage", "",
              f"- today risk used: ${st['risk_used_today']:.2f} / ${r['max_daily_risk_usd']}",
              f"- open exposure: ${st['open_exposure']:.2f} / ${r['max_total_exposure_usd']}",
              f"- open positions: {st['open_positions']} / {r['max_open_positions']}",
              f"- realized P&L today: ${st['realized_pnl_today']:+.2f} "
              f"(halt at -${r['daily_loss_halt_usd']})",
              "", "## Calibration (settled paper trades)", ""]
    if cal.get("n_settled", 0) == 0:
        lines.append("_no settled trades yet_")
    else:
        better = "MODEL better" if cal["brier_model"] < cal["brier_market"] else "MARKET better"
        lines += [f"- settled: {cal['n_settled']} | win rate: {cal['win_rate']:.0%} | "
                  f"realized P&L: ${cal['realized_pnl']:+.2f}",
                  f"- Brier(model) {cal['brier_model']} vs Brier(market) {cal['brier_market']} "
                  f"-> {better}"]
    g = cfg["live_gate"]
    ok_n = cal.get("n_settled", 0) >= g["min_settled_trades"]
    ok_b = (cal.get("n_settled", 0) > 0
            and cal.get("brier_model", 9) < min(g["max_brier"], cal.get("brier_market", 9)))
    ok_p = cal.get("realized_pnl", -1) > 0
    lines += ["", "## Live gate", "",
              f"- [{'x' if ok_n else ' '}] settled trades >= {g['min_settled_trades']} "
              f"(now: {cal.get('n_settled', 0)})",
              f"- [{'x' if ok_b else ' '}] Brier(model) < min({g['max_brier']}, Brier(market))",
              f"- [{'x' if ok_p else ' '}] paper P&L positive",
              "",
              f"**{'GATE OPEN - review going live together' if all((ok_n, ok_b, ok_p)) else 'GATE CLOSED - stay on paper'}**",
              ""]
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"report_{today}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")


def cmd_status(_args) -> None:
    out = {**ledger.stats(), **ledger.calibration(),
           "pending_live_orders": len(ledger.pending_trades())}
    print(json.dumps(out, indent=2))


def cmd_pending(_args) -> None:
    rows = ledger.pending_trades()
    if not rows:
        print("no pending live orders")
        return
    for t in rows:
        print(f"  #{t['id']} {t['ticker']} {t['side'].upper()} x{t['contracts']} "
              f"@ {t['price'] * 100:.1f}c cost=${t['cost_usd']:.2f} "
              f"edge={t['edge_net']:+.3f} q={t['q_consensus']:.2f}")
    print(f"{len(rows)} pending. Execute: python -m src.pipeline execute-live --confirmed")


def cmd_execute_live(args) -> None:
    if not args.confirmed:
        print("REFUSED: execute-live requires --confirmed "
              "(human approval or live.require_confirm=false auto-policy).")
        sys.exit(2)
    cfg = load_config()
    if not live_active(cfg):
        print("REFUSED: mode is not live or live.enabled is false in config.yaml.")
        sys.exit(2)
    from .live import KalshiLive, LiveAuthError
    try:
        client = KalshiLive()
    except LiveAuthError as e:
        print(f"AUTH ERROR: {e}")
        sys.exit(2)
    rows = ledger.pending_trades()
    if args.id:
        rows = [t for t in rows if t["id"] == args.id]
    ok = failed = 0
    for t in rows:
        try:
            resp = client.place_limit(t["ticker"], t["side"], t["contracts"], t["price"])
            order_id = (resp.get("order") or {}).get("order_id") or resp.get("order_id") or "?"
            ledger.mark_placed(t["id"], str(order_id))
            ok += 1
            print(f"PLACED #{t['id']} {t['ticker']} {t['side'].upper()} x{t['contracts']} "
                  f"@ {t['price'] * 100:.1f}c order_id={order_id}")
        except Exception as e:
            failed += 1
            print(f"FAILED #{t['id']} {t['ticker']}: {e}")
    print(f"done: {ok} placed, {failed} failed, "
          f"{len(ledger.pending_trades())} still pending")


def cmd_cancel_pending(args) -> None:
    rows = ledger.pending_trades()
    if args.id:
        rows = [t for t in rows if t["id"] == args.id]
    for t in rows:
        ledger.void_trade(t["id"], args.reason or "cancelled by user")
        print(f"VOIDED #{t['id']} {t['ticker']}")
    print(f"done: {len(rows)} voided")


def cmd_live_check(_args) -> None:
    """Validate live credentials + connectivity without placing anything."""
    from .live import KalshiLive, LiveAuthError
    cfg = load_config()
    print(f"config: mode={cfg['mode']} live.enabled={cfg.get('live', {}).get('enabled')} "
          f"require_confirm={cfg.get('live', {}).get('require_confirm')}")
    try:
        client = KalshiLive()
    except LiveAuthError as e:
        print(f"NOT READY: {e}")
        sys.exit(1)
    bal = client.balance()
    pos = client.positions()
    n_pos = len(pos.get("market_positions") or pos.get("positions") or [])
    print(f"READY: balance={bal} | open API positions={n_pos}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan").set_defaults(fn=cmd_scan)
    p = sub.add_parser("rules")
    p.add_argument("ticker")
    p.set_defaults(fn=cmd_rules)
    p = sub.add_parser("decide")
    p.add_argument("--research", required=True)
    p.set_defaults(fn=cmd_decide)
    sub.add_parser("settle").set_defaults(fn=cmd_settle)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("pending").set_defaults(fn=cmd_pending)
    p = sub.add_parser("execute-live")
    p.add_argument("--confirmed", action="store_true")
    p.add_argument("--id", type=int, default=None)
    p.set_defaults(fn=cmd_execute_live)
    p = sub.add_parser("cancel-pending")
    p.add_argument("--id", type=int, default=None)
    p.add_argument("--reason", default="")
    p.set_defaults(fn=cmd_cancel_pending)
    sub.add_parser("live-check").set_defaults(fn=cmd_live_check)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
