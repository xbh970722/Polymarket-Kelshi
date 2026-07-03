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
from .kalshi_client import KalshiPublic, taker_fee_usd
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
        # live mode: bankroll = real account balance; tighten every cap to the
        # live sub-limits; edge bar from live config (VALUES.md #2/#5/#5a)
        from .live import KalshiLive, LiveAuthError
        try:
            balance = float(KalshiLive().balance().get("balance_dollars") or 0)
        except LiveAuthError as e:
            print(f"AUTH ERROR: {e}")
            sys.exit(2)
        lv = cfg["live"]
        cfg["sizing"]["bankroll_usd"] = min(cfg["sizing"]["bankroll_usd"], balance)
        print(f"live bankroll: ${cfg['sizing']['bankroll_usd']:.2f} (account balance)")
        cfg["risk"]["max_per_trade_usd"] = min(cfg["risk"]["max_per_trade_usd"],
                                               lv["max_per_trade_usd"])
        for cap in ("max_daily_risk_usd", "max_total_exposure_usd",
                    "max_open_positions", "daily_loss_halt_usd"):
            if lv.get(cap) is not None:
                cfg["risk"][cap] = min(cfg["risk"][cap], lv[cap])
        cfg["edge"]["min_edge_after_fees"] = max(
            cfg["edge"]["min_edge_after_fees"],
            lv.get("live_min_edge_after_fees",
                   cfg["edge"].get("live_min_edge_after_fees", 0.05)))
    research = json.loads(Path(args.research).read_text(encoding="utf-8"))
    api = KalshiPublic()
    placed = skipped = 0
    for item in research["items"]:
        ticker = item["ticker"]
        if ledger.has_open_position(ticker, cfg["mode"]):
            print(f"SKIP  {ticker}: already holding an open {cfg['mode']} position")
            skipped += 1
            continue
        mn = api.market_norm(ticker)
        ya, na, yb = mn["yes_ask"], mn["no_ask"], mn["yes_bid"]
        if not (0.01 <= ya <= 0.99 and 0.01 <= na <= 0.99):
            print(f"SKIP  {ticker}: no live two-sided quote")
            skipped += 1
            continue
        d = engine.decide(item["q_claude"], item["q_codex"], ya, na, cfg)
        if d.action == "trade" and is_live:
            hc_cap = _conviction_cap(item, d, (ya + yb) / 2 if yb else ya, cfg)
            if hc_cap:
                cfg_hc = {**cfg, "risk": {**cfg["risk"], "max_per_trade_usd": hc_cap}}
                d = engine.decide(item["q_claude"], item["q_codex"], ya, na, cfg_hc)
                print(f"HIGH-CONVICTION {ticker}: cap raised to ${hc_cap:.2f}")
        if d.action == "skip":
            print(f"SKIP  {ticker}: {d.reason}")
            skipped += 1
            continue
        veto = engine.check_risk(ledger.stats(cfg["mode"]), d.cost_usd, cfg)
        if veto:
            print(f"VETO  {ticker}: {veto}")
            skipped += 1
            continue
        market_prob = round((yb + ya) / 2, 4) if yb else round(ya, 4)
        status = "pending" if is_live else "open"
        trade_id = ledger.insert_trade(
            mode=cfg["mode"], ticker=ticker, title=item.get("title", ""),
            side=d.side, price=d.price, contracts=d.contracts,
            cost_usd=d.cost_usd, fee_usd=d.fee_usd,
            q_claude=item["q_claude"], q_codex=item["q_codex"],
            q_consensus=d.q_consensus, market_prob=market_prob,
            edge_net=d.edge_net, rationale=item.get("rationale", ""),
            status=status)
        _assign_exit_plan(trade_id, d.side, d.price, d.q_consensus, cfg)
        placed += 1
        tag = "LIVE-PENDING" if is_live else "PAPER"
        print(f"{tag} {ticker}: {d.side.upper()} x{d.contracts} @ {d.price * 100:.1f}c "
              f"cost=${d.cost_usd:.2f} (fee ${d.fee_usd:.2f}) edge={d.edge_net:+.3f} "
              f"q={d.q_consensus:.2f} vs mkt={market_prob:.2f}")
    if is_live and placed:
        print(f"NOTE: {placed} live order(s) are PENDING confirmation. "
              f"Review with 'pending', then 'execute-live --confirmed'.")
    print(f"done: {placed} orders ({'live-pending' if is_live else 'paper'}), {skipped} skipped")


def _conviction_cap(item: dict, d, market_mid: float, cfg: dict) -> float | None:
    """VALUES.md #5a '极其确定' tier: edge >=10pts + family agreement + all four
    blind estimators on the same side of the market. Returns the raised cap or None."""
    hc = cfg["live"].get("high_conviction") or {}
    if d.edge_net < hc.get("min_edge", 0.10):
        return None
    if abs(item["q_claude"] - item["q_codex"]) > hc.get("max_family_divergence", 0.05):
        return None
    if hc.get("require_all_estimators", True):
        q_all = item.get("q_all") or []
        if len(q_all) < 4:
            return None
        if d.side == "yes" and not all(q > market_mid for q in q_all):
            return None
        if d.side == "no" and not all(q < market_mid for q in q_all):
            return None
    return cfg["live"].get("high_conviction_max_usd")


def _assign_exit_plan(trade_id: int, side: str, entry_price: float,
                      q_consensus: float, cfg: dict) -> engine.ExitPlan:
    q_side = q_consensus if side == "yes" else 1 - q_consensus
    plan = engine.plan_exit(q_side, entry_price, cfg)
    ts_row = [t for t in ledger.open_trades() + ledger.pending_trades() if t["id"] == trade_id]
    base = ts_row[0]["ts"] if ts_row else dt.datetime.now().isoformat(timespec="seconds")
    review_ts = (dt.datetime.fromisoformat(base)
                 + dt.timedelta(days=plan.review_after_days)).isoformat(timespec="seconds")
    ledger.set_exit_plan(trade_id, plan.exit_type, plan.target_price, plan.stop_price, review_ts)
    return plan


def cmd_manage(_args) -> None:
    """Mechanical swing management: take-profit / stop-loss exits + flag review-due holds."""
    cfg = load_config()
    if not cfg.get("swing", {}).get("enabled", False):
        print("swing management disabled in config")
        return
    is_live = live_active(cfg)
    api = KalshiPublic()
    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    exited = flagged = held = 0
    for t in ledger.open_trades():
        if t.get("exit_type") is None:                 # backfill plan for legacy positions
            _assign_exit_plan(t["id"], t["side"], t["price"], t["q_consensus"] or 0, cfg)
            t = next((x for x in ledger.open_trades() if x["id"] == t["id"]), t)
        try:
            m = api.market_norm(t["ticker"])
        except Exception as e:
            print(f"WARN  {t['ticker']}: {e}")
            continue
        exit_bid = m["yes_bid"] if t["side"] == "yes" else m["no_bid"]
        action, px = engine.check_exit(t.get("target_price") or 0, t.get("stop_price") or 0, exit_bid)
        if action and px > 0:
            fee = taker_fee_usd(px, t["contracts"])
            pnl = round(t["contracts"] * px - fee - t["cost_usd"], 2)
            if t["mode"] == "live":            # real position -> real sell (reduce_only)
                if not is_live:
                    print(f"HOLD  {t['ticker']}: live position but live mode disabled - not selling")
                    continue
                from .live import KalshiLive
                try:
                    KalshiLive().place_exit(t["ticker"], t["side"], t["contracts"], px)
                except Exception as e:
                    print(f"LIVE EXIT FAILED {t['ticker']}: {e}")
                    continue
            ledger.close_position(t["id"], px, pnl, f"{action}@{px * 100:.0f}c")
            exited += 1
            print(f"EXIT  {t['ticker']}: {action} sell x{t['contracts']} @ {px * 100:.0f}c "
                  f"pnl=${pnl:+.2f}")
        elif t.get("review_after_ts") and t["review_after_ts"] <= now_iso:
            flagged += 1
            tgt = (t.get("target_price") or 0) * 100
            print(f"REVIEW-DUE {t['ticker']}: held since {t['ts'][:10]} entry {t['price'] * 100:.0f}c "
                  f"mark {exit_bid * 100:.0f}c target {tgt:.0f}c -> ensemble re-judge hold/modify/exit")
        else:
            held += 1
    print(f"done: {exited} exited, {flagged} flagged for review, {held} holding")


def _decisive_ioc(client, api, ticker: str, side: str, contracts: int,
                  q_model: float, min_edge: float, slippage: float = 0.01):
    """Decisive fill: re-quote fresh, cross up to `slippage` above the ask, but only
    if the edge STILL clears the bar at that worst-case price. Returns
    (filled_count, avg_price, fee, order_id) or (0, reason, None, None)."""
    mn = api.market_norm(ticker)
    ask = mn["yes_ask"] if side == "yes" else mn["no_ask"]
    if not (0.01 <= ask <= 0.99):
        return 0, "no fresh quote", None, None
    limit_px = round(min(ask + slippage, 0.99), 4)
    q_side = q_model if side == "yes" else 1 - q_model
    if q_side - limit_px - taker_fee_usd(limit_px, 1) < min_edge:
        return 0, f"edge below bar at crossed price {limit_px:.3f}", None, None
    resp = client.place_limit(ticker, side, contracts, limit_px)
    filled = int(float(resp.get("fill_count") or 0))
    if filled < 1:
        return 0, "IOC no fill even crossed", None, None
    avg_px = float(resp.get("average_fill_price") or limit_px)
    if side == "no":                     # exchange reports fills in YES-leg terms
        avg_px = round(1.0 - avg_px, 4)
    fee_per = float(resp.get("average_fee_paid") or 0) * filled
    fee = round(fee_per, 2) if fee_per else taker_fee_usd(avg_px, filled)
    return filled, avg_px, fee, str(resp.get("order_id") or "?")


def cmd_shortcycle(_args) -> None:
    """Hourly quant lane: model hourly crypto strikes, trade real micro-edges (no LLM)."""
    cfg = load_config()
    sc = cfg.get("shortcycle", {})
    if not sc.get("enabled"):
        print("shortcycle disabled")
        return
    if not live_active(cfg):
        print("shortcycle requires live mode (it exists to generate real settled samples)")
        return
    from .live import KalshiLive, LiveAuthError
    from .shortcycle import candidates, candidates_15m
    try:
        client = KalshiLive()
        balance = float(client.balance().get("balance_dollars") or 0)
    except LiveAuthError as e:
        print(f"AUTH ERROR: {e}")
        return
    # dedicated sub-budget: today's live cost on shortcycle series tickers
    today = dt.date.today().isoformat()
    prefixes = tuple(sc["series"]) + tuple(sc.get("series_15m", []))
    spent = sum(t["cost_usd"] for t in ledger.open_trades() + ledger.pending_trades()
                if t["mode"] == "live" and t["ticker"].startswith(prefixes)
                and t["ts"].startswith(today))
    cands = candidates(cfg) + candidates_15m(cfg)
    print(f"shortcycle: {len(cands)} candidate strikes | balance ${balance:.2f} | "
          f"today spent ${spent:.2f}/{sc['daily_budget_usd']:.2f}")
    api = KalshiPublic()
    placed = 0
    for c in sorted(cands, key=lambda x: -abs(x["q_model"] - x["mid"])):
        if spent >= sc["daily_budget_usd"]:
            print("budget: shortcycle daily budget reached")
            break
        if ledger.has_open_position(c["ticker"], "live"):
            continue
        min_edge = (sc.get("min_edge_by_series") or {}).get(c["series"],
                                                            sc["min_edge_after_fees"])
        cfg_sc = {**cfg,
                  "edge": {**cfg["edge"], "min_edge_after_fees": min_edge,
                           "consensus_max_divergence": 1.0},
                  "sizing": {**cfg["sizing"], "bankroll_usd": min(balance, cfg["sizing"]["bankroll_usd"])},
                  "risk": {**cfg["risk"], "max_per_trade_usd": sc["max_per_trade_usd"]}}
        d = engine.decide(c["q_model"], c["q_model"], c["yes_ask"], c["no_ask"], cfg_sc)
        if d.action != "trade":
            continue
        contracts = min(d.contracts, sc.get("max_contracts", 3))
        est_cost = round(contracts * (d.price + sc.get("slippage", 0.01)) + 0.02, 2)
        veto = engine.check_risk(ledger.stats("live"), est_cost, cfg_sc)
        if veto:
            print(f"VETO  {c['ticker']}: {veto}")
            continue
        try:
            n, px, fee, order_id = _decisive_ioc(client, api, c["ticker"], d.side, contracts,
                                                 c["q_model"], min_edge, sc.get("slippage", 0.01))
        except Exception as e:
            print(f"FAILED {c['ticker']}: {e}")
            continue
        if n < 1:
            print(f"PASS  {c['ticker']}: {px}")
            continue
        cost = round(n * px + fee, 2)
        tid = ledger.insert_trade(
            mode="live", ticker=c["ticker"], title=f"shortcycle {c['series']} strike {c['strike']}",
            side=d.side, price=px, contracts=n, cost_usd=cost, fee_usd=fee,
            q_claude=c["q_model"], q_codex=c["q_model"], q_consensus=c["q_model"],
            market_prob=c["mid"], edge_net=d.edge_net,
            rationale=f"shortcycle terminal model: spot {c['spot']:.0f}, sigma_min "
                      f"{c['sigma_min']:.5f}, tau {c['tau_min']}m", status="open")
        ledger.set_exit_plan(tid, "hold", 0.0, 0.0,
                             (dt.datetime.now() + dt.timedelta(days=1)).isoformat(timespec="seconds"))
        ledger.mark_placed(tid, order_id)
        spent += cost
        placed += 1
        print(f"LIVE  {c['ticker']}: {d.side.upper()} x{n} @ {px * 100:.1f}c "
              f"cost=${cost:.2f} q_model={c['q_model']:.2f} vs mkt={c['mid']:.2f} "
              f"tau={c['tau_min']}m order={order_id}")
    print(f"done: {placed} shortcycle orders")


def cmd_weather(_args) -> None:
    """Weather lane: daily high-temp markets priced from NWS obs + hourly forecast."""
    cfg = load_config()
    wc = cfg.get("weather", {})
    if not wc.get("enabled"):
        print("weather lane disabled")
        return
    if not live_active(cfg):
        print("weather lane requires live mode")
        return
    from .live import KalshiLive, LiveAuthError
    from .weather import candidates
    try:
        client = KalshiLive()
        balance = float(client.balance().get("balance_dollars") or 0)
    except LiveAuthError as e:
        print(f"AUTH ERROR: {e}")
        return
    today = dt.date.today().isoformat()
    spent = sum(t["cost_usd"] for t in ledger.open_trades() + ledger.pending_trades()
                if t["mode"] == "live" and t["ticker"].startswith("KXHIGH")
                and t["ts"].startswith(today))
    cands = candidates(cfg)
    print(f"weather: {len(cands)} priced buckets | spent ${spent:.2f}/{wc['daily_budget_usd']:.2f}")
    api = KalshiPublic()
    placed = 0
    per_city: dict = {}
    for c in sorted(cands, key=lambda x: -abs(x["q_model"] - x["mid"])):
        if spent >= wc["daily_budget_usd"]:
            print("budget: weather daily budget reached")
            break
        if per_city.get(c["series"], 0) >= wc.get("max_trades_per_city_per_day", 1):
            continue
        if ledger.has_open_position(c["ticker"], "live"):
            continue
        cfg_w = {**cfg,
                 "edge": {**cfg["edge"], "min_edge_after_fees": wc["min_edge_after_fees"],
                          "consensus_max_divergence": 1.0},
                 "sizing": {**cfg["sizing"], "bankroll_usd": min(balance, cfg["sizing"]["bankroll_usd"])},
                 "risk": {**cfg["risk"], "max_per_trade_usd": wc["max_per_trade_usd"]}}
        d = engine.decide(c["q_model"], c["q_model"], c["yes_ask"], c["no_ask"], cfg_w)
        if d.action != "trade":
            continue
        contracts = min(d.contracts, wc.get("max_contracts", 3))
        est_cost = round(contracts * (d.price + 0.01) + 0.02, 2)
        veto = engine.check_risk(ledger.stats("live"), est_cost, cfg_w)
        if veto:
            print(f"VETO  {c['ticker']}: {veto}")
            continue
        try:
            n, px, fee, order_id = _decisive_ioc(client, api, c["ticker"], d.side, contracts,
                                                 c["q_model"], wc["min_edge_after_fees"])
        except Exception as e:
            print(f"FAILED {c['ticker']}: {e}")
            continue
        if n < 1:
            print(f"PASS  {c['ticker']}: {px}")
            continue
        cost = round(n * px + fee, 2)
        tid = ledger.insert_trade(
            mode="live", ticker=c["ticker"], title=f"weather {c['series']}",
            side=d.side, price=px, contracts=n, cost_usd=cost, fee_usd=fee,
            q_claude=c["q_model"], q_codex=c["q_model"], q_consensus=c["q_model"],
            market_prob=c["mid"], edge_net=d.edge_net,
            rationale=f"NWS model: mu {c['mu']}F sigma {c['sigma']} obs_max {c['obs_max']} "
                      f"fc_max {c['fc_max']} local_h {c['local_hour']}", status="open")
        ledger.set_exit_plan(tid, "hold", 0.0, 0.0,
                             (dt.datetime.now() + dt.timedelta(days=1)).isoformat(timespec="seconds"))
        ledger.mark_placed(tid, order_id)
        spent += cost
        per_city[c["series"]] = per_city.get(c["series"], 0) + 1
        placed += 1
        print(f"LIVE  {c['ticker']}: {d.side.upper()} x{n} @ {px * 100:.1f}c "
              f"cost=${cost:.2f} q_model={c['q_model']:.2f} vs mkt={c['mid']:.2f} "
              f"mu={c['mu']}F sigma={c['sigma']} order={order_id}")
    print(f"done: {placed} weather orders")


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
        lines += ["| ticker | side | qty | entry | mark | target | plan | unreal P&L | model q |",
                  "|---|---|---|---|---|---|---|---|---|"]
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
            tgt = t.get("target_price") or 0
            tgt_s = f"{tgt * 100:.0f}c" if tgt else "—"
            plan = t.get("exit_type") or "?"
            lines.append(f"| {t['ticker']} | {t['side']} | {t['contracts']} | "
                         f"{t['price'] * 100:.1f}c | {mark_s} | {tgt_s} | {plan} | {unreal:+.2f} | "
                         f"{t['q_consensus']:.2f} |")
        lines += ["", f"unrealized total: **{unreal_total:+.2f} USD**"]
    sw = ledger.swing_summary()
    if sw["n_closed"]:
        lines += ["", "## Swing exits (closed before settlement)", "",
                  f"- {sw['n_closed']} closed | realized swing P&L: **${sw['swing_pnl']:+.2f}** "
                  f"(excluded from Brier — no resolved outcome)"]
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


def _lane_of(ticker: str) -> str:
    if ticker.startswith(("KXBTCD", "KXETHD")) or "15M" in ticker.split("-")[0]:
        return "shortcycle"
    if ticker.startswith("KXHIGH"):
        return "weather"
    return "ensemble"


def cmd_journal(_args) -> None:
    """Daily P&L journal: per-lane realized/fills today + running calibration + CSV history."""
    cfg = load_config()
    today = dt.date.today().isoformat()
    con = ledger._conn()
    settled_today = [dict(r) for r in con.execute(
        "SELECT * FROM trades WHERE settled_ts LIKE ? || '%' AND status IN ('settled','closed')",
        (today,))]
    fills_today = [dict(r) for r in con.execute(
        "SELECT * FROM trades WHERE ts LIKE ? || '%' AND status != 'voided'", (today,))]
    all_settled = [dict(r) for r in con.execute(
        "SELECT * FROM trades WHERE status='settled' AND result IN ('yes','no')")]

    lanes = {"shortcycle": [], "weather": [], "ensemble": []}
    for t in settled_today:
        lanes[_lane_of(t["ticker"])].append(t)
    realized = {k: round(sum(t["pnl_usd"] or 0 for t in v), 2) for k, v in lanes.items()}
    total_realized = round(sum(realized.values()), 2)

    brier = {}
    for lane in lanes:
        rows = [t for t in all_settled if _lane_of(t["ticker"]) == lane]
        if rows:
            bm = sum((t["q_consensus"] - (1.0 if t["result"] == "yes" else 0.0)) ** 2
                     for t in rows) / len(rows)
            bk = sum((t["market_prob"] - (1.0 if t["result"] == "yes" else 0.0)) ** 2
                     for t in rows) / len(rows)
            brier[lane] = (len(rows), round(bm, 4), round(bk, 4))

    balance = None
    if live_active(cfg):
        try:
            from .live import KalshiLive
            balance = float(KalshiLive().balance().get("balance_dollars") or 0)
        except Exception:
            pass

    st = ledger.stats("live")
    lines = [f"# 交易日志 {today}", "",
             f"- 实时余额: {'$%.2f' % balance if balance is not None else 'n/a'} | "
             f"live 敞口 ${st['open_exposure']:.2f} | 今日已实现 **${total_realized:+.2f}**",
             f"- 今日成交 {len(fills_today)} 笔 | 今日结算 {len(settled_today)} 笔", "",
             "## 分通道", ""]
    for lane in ("shortcycle", "weather", "ensemble"):
        b = brier.get(lane)
        cal = (f"Brier {b[1]} vs 市场 {b[2]} (n={b[0]})" if b else "尚无结算样本")
        lines.append(f"- **{lane}**: 今日已实现 ${realized[lane]:+.2f} | {cal}")
    lines += ["", "## 今日结算明细", ""]
    if settled_today:
        for t in settled_today:
            tag = t["result"] or (t.get("rationale") or "")[-20:]
            lines.append(f"- {t['ticker']} {t['side']} x{t['contracts']} @ "
                         f"{t['price'] * 100:.0f}c -> {t['status']}({tag}) "
                         f"pnl ${t['pnl_usd'] or 0:+.2f} | 模型 q={t['q_consensus']:.2f} "
                         f"市场 {t['market_prob']:.2f}")
    else:
        lines.append("_无_")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"journal_{today}.md").write_text("\n".join(lines), encoding="utf-8")

    csv = REPORTS / "pnl_history.csv"
    header = "date,realized_today,balance,fills_today,settled_today,live_exposure\n"
    row = (f"{today},{total_realized},{balance if balance is not None else ''},"
           f"{len(fills_today)},{len(settled_today)},{st['open_exposure']:.2f}\n")
    if csv.exists():
        content = [l for l in csv.read_text(encoding="utf-8").splitlines(True)
                   if not l.startswith(today)]
        csv.write_text("".join(content) + row, encoding="utf-8")
    else:
        csv.write_text(header + row, encoding="utf-8")
    print(f"journal written: realized today ${total_realized:+.2f}, "
          f"{len(settled_today)} settled, {len(fills_today)} fills")


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
    sub.add_parser("manage").set_defaults(fn=cmd_manage)
    sub.add_parser("shortcycle").set_defaults(fn=cmd_shortcycle)
    sub.add_parser("weather").set_defaults(fn=cmd_weather)
    sub.add_parser("journal").set_defaults(fn=cmd_journal)
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
