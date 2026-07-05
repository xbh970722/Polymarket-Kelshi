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
import re
import sys
import uuid
from pathlib import Path

import yaml

from . import engine, ledger
from .kalshi_client import KalshiPublic, normalize_market, taker_fee_usd
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
            if t["mode"] == "live":            # real position -> real sell (reduce_only)
                if not is_live:
                    print(f"HOLD  {t['ticker']}: live position but live mode disabled - not selling")
                    continue
                from .live import KalshiLive
                try:
                    client_x = KalshiLive()
                except Exception as e:
                    print(f"LIVE EXIT FAILED {t['ticker']}: auth ({e})")
                    continue
                try:
                    resp = client_x.place_exit(t["ticker"], t["side"], t["contracts"], px)
                except RuntimeError as e:
                    st = _http_status(e)       # R4: parse status, don't substring-match
                    if st is not None and 400 <= st < 500:   # clean reject: untouched
                        print(f"LIVE EXIT FAILED {t['ticker']}: {e}")
                    else:                      # R3-CODEX-2: 5xx after possible execution
                        print(f"CRITICAL {t['ticker']}: exit outcome AMBIGUOUS ({str(e)[:90]}) "
                              f"— position may be partly closed; reconcile will compare books")
                    continue
                except Exception as e:
                    print(f"CRITICAL {t['ticker']}: exit outcome AMBIGUOUS "
                          f"({type(e).__name__}: {str(e)[:80]}) — reconcile will compare books")
                    continue
                # CODEX-A fix: close only what actually filled, at the real price
                filled = int(float(resp.get("fill_count") or resp.get("fill_count_fp") or 0))
                if filled < 1:
                    oid = resp.get("order_id")
                    if oid:
                        try:
                            client_x.cancel_order(str(oid))
                        except Exception:
                            pass
                    print(f"EXIT NOFILL {t['ticker']}: book gone, keep holding")
                    held += 1
                    continue
                # CODEX-1 CRITICAL fix: convert ONLY exchange-reported averages;
                # the px fallback is already in held-side frame.
                raw_avg = resp.get("average_fill_price")
                if raw_avg is not None and str(raw_avg) != "":
                    avg_px = float(raw_avg)
                    if t["side"] == "no":
                        avg_px = round(1.0 - avg_px, 4)
                else:
                    avg_px = px
                fee_paid = float(resp.get("average_fee_paid") or 0) * filled
                fee = round(fee_paid, 2) if fee_paid else taker_fee_usd(avg_px, filled)
                try:
                    ledger.split_close(t["id"], filled, avg_px, fee,
                                       f"{action}@{avg_px * 100:.0f}c")
                except Exception as e:   # R3-CODEX-2: exit FILLED but books didn't move
                    print(f"CRITICAL {t['ticker']}: EXIT FILLED x{filled} but split_close "
                          f"failed ({e}) — freezing #{t['id']} as unknown")
                    try:
                        ledger.mark_unknown(t["id"], f"exit filled x{filled}@{avg_px} "
                                                     f"but split_close failed")
                    except Exception:
                        pass
                    continue
                exited += 1
                print(f"EXIT  {t['ticker']}: {action} sell x{filled}/{t['contracts']} "
                      f"@ {avg_px * 100:.0f}c")
                continue
            fee = taker_fee_usd(px, t["contracts"])
            pnl = round(t["contracts"] * px - fee - t["cost_usd"], 2)
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


def _live_risk_overlay(cfg: dict) -> dict:
    """CODEX-6 HIGH fix: EVERY live lane must trade under the live sub-limits.
    Shortcycle/weather were checking risk against the paper-scale caps
    (daily_loss_halt $200 instead of $5). Returns cfg with merged risk."""
    lv = cfg.get("live", {})
    merged = {**cfg["risk"]}
    for cap in ("max_per_trade_usd", "max_daily_risk_usd", "max_total_exposure_usd",
                "max_open_positions", "daily_loss_halt_usd"):
        if lv.get(cap) is not None:
            merged[cap] = min(merged[cap], lv[cap])
    return {**cfg, "risk": merged}


class OrderAmbiguous(RuntimeError):
    """R3 5-reviewer consensus: raised when an order POST was ATTEMPTED but the
    outcome is unprovable (timeout, connection drop, 5xx, unparseable fill count).
    Callers must freeze the pre-submit intent row as 'unknown' — never retry,
    never void — until the reconcile fills-resolver proves what happened."""


def _http_status(err: Exception) -> int | None:
    """R4-FABLE-A MED fix: parse the status code from live._req's fixed error
    prefix ('METHOD path -> HTTP NNN: body'). A raw substring test over the whole
    text could match 'HTTP 4xx' INSIDE a 5xx response body and misclassify an
    ambiguous failure as a provable reject."""
    m = re.search(r"-> HTTP (\d{3}):", str(err))
    return int(m.group(1)) if m else None


def _decisive_ioc(client, api, ticker: str, side: str, contracts: int,
                  q_model: float, min_edge: float, slippage: float = 0.01,
                  price_cap: float = 0.99, max_cost_usd: float | None = None,
                  client_order_id: str | None = None):
    """Decisive fill: re-quote fresh, cross up to `slippage` above the ask, but only
    if the edge STILL clears the bar at that worst-case price. `price_cap` hard-limits
    the buy price in the favorite side's own terms (H7 fix, 2026-07-04): the IOC can
    NEVER fill above it, so favorites cannot leak into the extreme high-price zone
    where one loss wipes ~20 wins. Returns (filled, avg_price, fee, order_id) or
    (0, reason, None, None); a post-fill guard also rejects any fill above the cap."""
    mn = api.market_norm(ticker)
    ask = mn["yes_ask"] if side == "yes" else mn["no_ask"]
    if not (0.01 <= ask <= 0.99):
        return 0, "no fresh quote", None, None
    limit_px = round(min(ask + slippage, price_cap, 0.99), 4)
    if limit_px < ask:                   # cap sits below the ask -> would only fill worse
        return 0, f"ask {ask:.3f} above price_cap {price_cap:.3f}", None, None
    q_side = q_model if side == "yes" else 1 - q_model
    if q_side - limit_px - taker_fee_usd(limit_px, 1) < min_edge:
        return 0, f"edge below bar at crossed price {limit_px:.3f}", None, None
    # R3-C1/C6/C8 HIGH fix: the pre-scan cap check used a STALE price; recheck the
    # dollar cap at the fresh crossed limit — shrink to fit, or refuse to POST.
    if max_cost_usd is not None:
        while contracts > 1 and (contracts * limit_px
                                 + taker_fee_usd(limit_px, contracts)) > max_cost_usd + 1e-9:
            contracts -= 1
        if contracts * limit_px + taker_fee_usd(limit_px, contracts) > max_cost_usd + 1e-9:
            return 0, (f"fresh px {limit_px:.2f} busts cap ${max_cost_usd:.2f} "
                       f"even at 1 contract"), None, None
    try:
        resp = client.place_limit(ticker, side, contracts, limit_px,
                                  client_order_id=client_order_id)
    except RuntimeError as e:
        st = _http_status(e)
        if st is not None and 400 <= st < 500:   # provable exchange reject: no order
            return 0, f"rejected: {str(e)[:80]}", None, None
        raise OrderAmbiguous(str(e)[:120])          # 5xx/unparsed: may have executed
    except Exception as e:               # timeout/connection: POST may have landed
        raise OrderAmbiguous(f"{type(e).__name__}: {str(e)[:90]}")
    # R4-FABLE-A HIGH fix: a response IS in hand — any parse failure from payload
    # drift must FREEZE (ambiguous), never bubble out as a pre-submit-style void.
    try:
        # V2 responses use fill_count OR fill_count_fp depending on path (sell-path
        # test 2026-07-04: sells reported via _fp and were misread as no-fill)
        fill_raw = float(resp.get("fill_count") or resp.get("fill_count_fp") or 0)
        filled = int(fill_raw)
        if abs(fill_raw - filled) > 1e-9:   # R3-C3 HIGH: NEVER truncate a fractional
            raise OrderAmbiguous(f"fractional fill_count {fill_raw}")  # fill silently
        if filled < 1:
            oid = resp.get("order_id")
            if oid:                   # belt-and-suspenders: never leave a resting stray
                try:
                    client.cancel_order(str(oid))
                except Exception:
                    pass
            return 0, "IOC no fill even crossed", None, None
        # CODEX-1 CRITICAL fix: the YES-leg->held-side conversion applies ONLY to the
        # exchange-reported average; the limit_px fallback is ALREADY held-side frame.
        raw_avg = resp.get("average_fill_price")
        if raw_avg is not None and str(raw_avg) != "":
            avg_px = float(raw_avg)
            if side == "no":             # exchange reports fills in YES-leg terms
                avg_px = round(1.0 - avg_px, 4)
        else:
            avg_px = limit_px            # held-side frame already; no conversion
        if avg_px > price_cap + 1e-9:    # belt-and-suspenders: fill leaked past cap
            print(f"WARN {ticker}: fill {avg_px:.3f} exceeded cap {price_cap:.3f} "
                  f"(kept, flagged)")
        fee_per = float(resp.get("average_fee_paid") or 0) * filled
        fee = round(fee_per, 2) if fee_per else taker_fee_usd(avg_px, filled)
        return filled, avg_px, fee, str(resp.get("order_id") or "?")
    except OrderAmbiguous:
        raise
    except Exception as e:
        raise OrderAmbiguous(f"response parse failed: {type(e).__name__} {str(e)[:80]}")


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
    # dedicated sub-budget by LANE TITLE — ticker prefixes collide with the favorites
    # lane on the same series (bug #12: favorites' spend locked this lane out all day)
    spent = ledger.spent_today_by_title("shortcycle")
    budget = sc["daily_budget_usd"]
    extra = sc.get("budget_extra") or {}
    if extra.get("date") == dt.date.today().isoformat():
        budget += float(extra.get("usd", 0))          # self-expiring one-day top-up
    cands = candidates(cfg) + candidates_15m(cfg)
    print(f"shortcycle: {len(cands)} candidate strikes | balance ${balance:.2f} | "
          f"today spent ${spent:.2f}/{budget:.2f}")
    api = KalshiPublic()
    placed = 0
    for c in sorted(cands, key=lambda x: -abs(x["q_model"] - x["mid"])):
        if spent >= budget:
            print("budget: shortcycle daily budget reached")
            break
        if ledger.has_open_position(c["ticker"], "live"):
            continue
        # LAG-ONLY GATE (post-mortem 2026-07-03, 0/16 on certainty-fades): trade only
        # when the MODEL is more certain than the market — i.e. price moved and quotes
        # lag. Fading market certainty with a worse vol model is structurally -EV.
        if sc.get("lag_only", True):
            if abs(c["q_model"] - 0.5) < abs(c["mid"] - 0.5) + sc.get("lag_margin", 0.02):
                continue
        if "15M" in c["series"]:
            # correlation cap: crypto moves together — one 15m position across ALL coins
            # (R3-FABLE HIGH: active_trades includes 'unknown' ambiguous fills)
            open_15m = [t for t in ledger.active_trades("live")
                        if "15M" in t["ticker"].split("-")[0]]
            if open_15m:
                continue
        # per-window cap: multiple strikes of the same event window = one bet repeated
        window_key = c["ticker"].rsplit("-", 1)[0]
        if any(t["ticker"].startswith(window_key) for t in ledger.active_trades("live")):
            continue
        min_edge = (sc.get("min_edge_by_series") or {}).get(c["series"],
                                                            sc["min_edge_after_fees"])
        cfg_sc = _live_risk_overlay({**cfg,      # CODEX-6 HIGH: live sub-limits apply here too
                  "edge": {**cfg["edge"], "min_edge_after_fees": min_edge,
                           "consensus_max_divergence": 1.0},
                  "sizing": {**cfg["sizing"], "bankroll_usd": min(balance, cfg["sizing"]["bankroll_usd"])}})
        cfg_sc["risk"]["max_per_trade_usd"] = min(cfg_sc["risk"]["max_per_trade_usd"],
                                                  sc["max_per_trade_usd"])
        d = engine.decide(c["q_model"], c["q_model"], c["yes_ask"], c["no_ask"], cfg_sc)
        if d.action != "trade":
            continue
        contracts = min(d.contracts, sc.get("max_contracts", 3))
        est_cost = round(contracts * (d.price + sc.get("slippage", 0.01)) + 0.02, 2)
        if spent + est_cost > budget:            # CODEX-6 MED: veto on projected overshoot
            print("budget: next order would exceed shortcycle daily budget")
            break
        veto = engine.check_risk(ledger.stats("live"), est_cost, cfg_sc)
        if veto:
            print(f"VETO  {c['ticker']}: {veto}")
            continue
        # R3 5-reviewer consensus (CRITICAL): durable INTENT ROW before the POST.
        # A fill whose response is lost must never be invisible to the books.
        # R4-FABLE-A: pure UUID — a prefixed id risks a format-400 on EVERY order.
        coid = str(uuid.uuid4())
        try:
            tid = ledger.insert_trade(
                mode="live", ticker=c["ticker"],
                title=f"shortcycle {c['series']} strike {c['strike']}",
                side=d.side, price=d.price, contracts=contracts, cost_usd=est_cost,
                fee_usd=0.0,
                q_claude=c["q_model"], q_codex=c["q_model"], q_consensus=c["q_model"],
                market_prob=c["mid"], edge_net=d.edge_net,
                rationale=f"shortcycle terminal model: spot {c['spot']:.0f}, sigma_min "
                          f"{c['sigma_min']:.5f}, tau {c['tau_min']}m",
                status="pending", order_id=coid)
        except Exception as e:
            print(f"FAILED {c['ticker']}: intent write failed ({e}) — no order sent")
            continue
        try:
            n, px, fee, order_id = _decisive_ioc(
                client, api, c["ticker"], d.side, contracts, c["q_model"], min_edge,
                sc.get("slippage", 0.01),
                max_cost_usd=min(cfg_sc["risk"]["max_per_trade_usd"],
                                 round(budget - spent, 2)),
                client_order_id=coid)
        except OrderAmbiguous as e:
            ledger.mark_unknown(tid, f"submit ambiguous: {e}")
            print(f"CRITICAL {c['ticker']}: order outcome UNKNOWN ({e}) — "
                  f"row #{tid} frozen; reconcile resolves via fills")
            continue
        except Exception as e:
            ledger.void_trade(tid, f"pre-submit failure: {e}")
            print(f"FAILED {c['ticker']}: {e}")
            continue
        if n < 1:
            ledger.void_trade(tid, f"no fill: {px}")
            print(f"PASS  {c['ticker']}: {px}")
            continue
        cost = round(n * px + fee, 2)
        try:
            ledger.record_fill(tid, n, px, cost, fee, order_id)
            ledger.set_exit_plan(tid, "hold", 0.0, 0.0,
                                 (dt.datetime.now() + dt.timedelta(days=1)).isoformat(timespec="seconds"))
        except Exception as e:
            print(f"CRITICAL {c['ticker']}: FILLED x{n} but ledger write failed ({e}) "
                  f"— freezing #{tid} as unknown")
            try:
                ledger.mark_unknown(tid, f"filled x{n}@{px} but record_fill failed")
            except Exception:
                pass
            spent += cost
            continue
        spent += cost
        placed += 1
        print(f"LIVE  {c['ticker']}: {d.side.upper()} x{n} @ {px * 100:.1f}c "
              f"cost=${cost:.2f} q_model={c['q_model']:.2f} vs mkt={c['mid']:.2f} "
              f"tau={c['tau_min']}m order={order_id}")
    print(f"done: {placed} shortcycle orders")


def cmd_favorites(_args) -> None:
    """Favorite-harvest lane: buy the favorite side (yes OR no) in the price zone,
    direction-neutral so a single-direction move can't systematically help/hurt.
    Bets the documented favorite-longshot bias, not a per-market model edge."""
    cfg = load_config()
    fc = cfg.get("favorites", {})
    if not fc.get("enabled"):
        print("favorites lane disabled")
        return
    if not live_active(cfg):
        print("favorites requires live mode")
        return
    from .live import KalshiLive, LiveAuthError
    try:
        client = KalshiLive()
        balance = float(client.balance().get("balance_dollars") or 0)
    except LiveAuthError as e:
        print(f"AUTH ERROR: {e}")
        return
    # Drawdown-step review cadence (user 2026-07-03): every -$3 of cumulative loss
    # raises a review (Fable 5 adjusts strategy) but trading CONTINUES; only a hard
    # stop at N steps truly disables. Steps are tracked so each band fires once.
    import json
    import os
    realized = ledger.realized_by_title("favorite")
    step = fc.get("drawdown_step_usd", 3.0)
    hard_steps = fc.get("hard_stop_steps", 5)
    cur_step = int((-realized) // step) if realized < 0 else 0
    fav_state_path = "data/fav_review_state.json"
    fav_state = {"steps_reviewed": 0}
    if os.path.exists(fav_state_path):
        try:
            fav_state = json.load(open(fav_state_path, encoding="utf-8"))
        except Exception:
            pass
    if cur_step > fav_state.get("steps_reviewed", 0):
        json.dump({"triggered_ts": dt.datetime.now().isoformat(timespec="seconds"),
                   "lane": "favorites", "step": cur_step, "realized": realized,
                   "reason": f"favorites drawdown step {cur_step} (${realized:.2f}) -> "
                             f"review & ADJUST strategy, then continue trading"},
                  open("data/review_due_favorites.json", "w", encoding="utf-8"))
        fav_state["steps_reviewed"] = cur_step
        json.dump(fav_state, open(fav_state_path, "w", encoding="utf-8"))
        print(f"DRAWDOWN REVIEW: favorites ${realized:.2f} (step {cur_step}) -> "
              f"review raised, TRADING CONTINUES")
    if cur_step >= hard_steps:
        print(f"HARD STOP: favorites ${realized:.2f} ({cur_step} steps >= {hard_steps}) "
              f"-> lane paused pending user")
        return
    lo, hi = fc.get("zone", [0.85, 0.95])
    twmin, twmax = fc.get("tau_window_min", [10, 90])
    # OPUS-A HIGH fix: true daily spend incl. settled (same leak class as shortcycle);
    # daily_budget_usd is now an honest per-day cap, sized in config for throughput
    spent = ledger.spent_today_by_title("favorite")
    n_open = sum(1 for t in ledger.open_trades() if (t["title"] or "").startswith("favorite"))
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc)
    cands = []
    for series in fc["series"]:
        try:                                    # R3-CODEX-3 MED: paginate — one page
            markets_raw = api.open_markets(series)   # can truncate busy crypto series
        except Exception:
            continue
        for mr in markets_raw:
            m = normalize_market(mr)
            if m["status"] != "active" or not m["close_time"]:
                continue
            close = dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
            tau = (close - now).total_seconds() / 60
            if not (twmin <= tau <= twmax):
                continue
            if not (m["yes_bid"] > 0 and 0.01 <= m["yes_ask"] <= 0.99):
                continue
            fav_side = "yes" if (m["yes_bid"] + m["yes_ask"]) / 2 >= 0.5 else "no"
            fav_ask = m["yes_ask"] if fav_side == "yes" else m["no_ask"]
            if lo <= fav_ask <= hi:
                cands.append((series, m, fav_side, fav_ask))
    print(f"favorites: {len(cands)} favorites in zone | realized ${realized:+.2f} | "
          f"today spent ${spent:.2f}/{fc['daily_budget_usd']:.2f}")
    # bug #13 fix (unified via _live_risk_overlay, CODEX-6): favorites obeys the
    # global live brakes; its own per-trade cap merges on top
    cfg_gl = _live_risk_overlay(cfg)
    cfg_gl["risk"]["max_per_trade_usd"] = min(cfg_gl["risk"]["max_per_trade_usd"],
                                              fc.get("max_per_trade_usd", 2.0))
    placed = 0
    for series, m, side, ask in sorted(cands, key=lambda x: x[3]):    # cheapest favorite = most room
        if spent >= fc["daily_budget_usd"] or n_open >= fc.get("max_open", 3):
            break
        est_ct = (fc.get("max_contracts_by_series") or {}).get(
            series, fc.get("max_contracts", 2))
        est_cost_f = est_ct * ask + 0.03
        if spent + est_cost_f > fc["daily_budget_usd"]:   # CODEX-6 MED
            print("budget: next order would exceed favorites daily budget")
            break
        veto = engine.check_risk(ledger.stats("live"), est_cost_f, cfg_gl)
        if veto:
            print(f"VETO  {m['ticker']}: {veto}")
            break
        if ledger.has_open_position(m["ticker"], "live"):
            continue
        window = m["ticker"].rsplit("-", 1)[0]
        if any(t["ticker"].startswith(window)          # R3-FABLE HIGH: incl. unknown
               for t in ledger.active_trades("live")):
            continue
        # bet the structural bias, not a model edge -> pass edge check trivially
        n_ct = (fc.get("max_contracts_by_series") or {}).get(
            series, fc.get("max_contracts", 2))   # R4: same default as est_ct
        # R3 consensus (CRITICAL): durable intent row BEFORE the POST
        coid = str(uuid.uuid4())     # R4: pure UUID (no prefix; format-safe)
        try:
            tid = ledger.insert_trade(
                mode="live", ticker=m["ticker"], title=f"favorite {series}",
                side=side, price=ask, contracts=n_ct, cost_usd=round(est_cost_f, 2),
                fee_usd=0.0,
                q_claude=round(ask, 4), q_codex=round(ask, 4), q_consensus=round(ask, 4),
                # OPUS-A LOW fix: store market_prob in the SAME frame as q/side
                market_prob=round((m["yes_bid"] + m["yes_ask"]) / 2, 4) if side == "yes"
                            else round(1 - (m["yes_bid"] + m["yes_ask"]) / 2, 4),
                edge_net=0.0,
                rationale=f"favorite-harvest {side} (direction-neutral bias bet)",
                status="pending", order_id=coid)
        except Exception as e:
            print(f"FAILED {m['ticker']}: intent write failed ({e}) — no order sent")
            continue
        try:
            # H7 fix: no upward slippage (structural-bias bet, don't chase) + hard
            # price cap at the zone top so a fill can never land in the extreme band.
            n, px, fee, oid = _decisive_ioc(
                client, api, m["ticker"], side, n_ct,
                1.0 if side == "yes" else 0.0, -1.0,
                slippage=0.0, price_cap=hi,
                max_cost_usd=min(cfg_gl["risk"]["max_per_trade_usd"],
                                 round(fc["daily_budget_usd"] - spent, 2)),
                client_order_id=coid)
        except OrderAmbiguous as e:
            ledger.mark_unknown(tid, f"submit ambiguous: {e}")
            print(f"CRITICAL {m['ticker']}: order outcome UNKNOWN ({e}) — "
                  f"row #{tid} frozen; reconcile resolves via fills")
            continue
        except Exception as e:
            ledger.void_trade(tid, f"pre-submit failure: {e}")
            print(f"FAILED {m['ticker']}: {e}")
            continue
        if n < 1:
            ledger.void_trade(tid, f"no fill: {px}")
            continue
        cost = round(n * px + fee, 2)
        try:
            ledger.record_fill(tid, n, px, cost, fee, oid)
            ledger.set_exit_plan(tid, "hold", 0.0, 0.0,
                                 (dt.datetime.now() + dt.timedelta(days=1)).isoformat(timespec="seconds"))
        except Exception as e:                    # CODEX-1 HIGH: fill exists on exchange!
            print(f"CRITICAL {m['ticker']}: FILLED x{n} @ {px*100:.0f}c (order {oid}) but "
                  f"ledger write failed ({e}) — freezing #{tid} as unknown")
            try:
                ledger.mark_unknown(tid, f"filled x{n}@{px} but record_fill failed")
            except Exception:
                pass
            spent += cost
            continue
        spent += cost
        n_open += 1
        placed += 1
        print(f"LIVE  {m['ticker']}: FAV {side.upper()} x{n} @ {px*100:.0f}c cost=${cost:.2f} "
              f"order={oid}")
    print(f"done: {placed} favorite orders")


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
    spent = ledger.spent_today_by_title("weather")   # OPUS-A HIGH fix (leak class)
    cands = candidates(cfg)
    print(f"weather: {len(cands)} priced buckets | spent ${spent:.2f}/{wc['daily_budget_usd']:.2f}")
    api = KalshiPublic()
    placed = 0
    # FABLE-C MED fix: per-city daily count from the LEDGER, not an in-process dict
    # that reset every 7-minute loop invocation (cap was per-run, not per-day)
    today = dt.date.today().isoformat()
    per_city: dict = {}
    for t in ledger.active_trades("live"):    # R4-FABLE-A LOW: incl. unknown rows —
        ttl = t.get("title") or ""            # an ambiguous fill still occupies the
        if ttl.startswith("weather") and t["ts"].startswith(today):   # city slot
            s = ttl.split(" ")[-1]
            per_city[s] = per_city.get(s, 0) + 1
    con_w = ledger._conn()
    for r in con_w.execute("SELECT title FROM trades WHERE ts LIKE ? || '%' AND "
                           "status IN ('settled','closed') AND title LIKE 'weather%'",
                           (today,)):
        s = (r["title"] or "").split(" ")[-1]
        per_city[s] = per_city.get(s, 0) + 1
    for c in sorted(cands, key=lambda x: -abs(x["q_model"] - x["mid"])):
        if spent >= wc["daily_budget_usd"]:
            print("budget: weather daily budget reached")
            break
        if per_city.get(c["series"], 0) >= wc.get("max_trades_per_city_per_day", 1):
            continue
        if ledger.has_open_position(c["ticker"], "live"):
            continue
        cfg_w = _live_risk_overlay({**cfg,       # CODEX-6 HIGH: live sub-limits apply here too
                 "edge": {**cfg["edge"], "min_edge_after_fees": wc["min_edge_after_fees"],
                          "consensus_max_divergence": 1.0},
                 "sizing": {**cfg["sizing"], "bankroll_usd": min(balance, cfg["sizing"]["bankroll_usd"])}})
        cfg_w["risk"]["max_per_trade_usd"] = min(cfg_w["risk"]["max_per_trade_usd"],
                                                 wc["max_per_trade_usd"])
        d = engine.decide(c["q_model"], c["q_model"], c["yes_ask"], c["no_ask"], cfg_w)
        if d.action != "trade":
            continue
        contracts = min(d.contracts, wc.get("max_contracts", 3))
        est_cost = round(contracts * (d.price + 0.01) + 0.02, 2)
        if spent + est_cost > wc["daily_budget_usd"]:   # CODEX-6 MED
            print("budget: next order would exceed weather daily budget")
            break
        veto = engine.check_risk(ledger.stats("live"), est_cost, cfg_w)
        if veto:
            print(f"VETO  {c['ticker']}: {veto}")
            continue
        # R3 consensus (CRITICAL): durable intent row BEFORE the POST
        coid = str(uuid.uuid4())     # R4: pure UUID (no prefix; format-safe)
        try:
            tid = ledger.insert_trade(
                mode="live", ticker=c["ticker"], title=f"weather {c['series']}",
                side=d.side, price=d.price, contracts=contracts, cost_usd=est_cost,
                fee_usd=0.0,
                q_claude=c["q_model"], q_codex=c["q_model"], q_consensus=c["q_model"],
                market_prob=c["mid"], edge_net=d.edge_net,
                rationale=f"NWS model: mu {c['mu']}F sigma {c['sigma']} obs_max {c['obs_max']} "
                          f"fc_max {c['fc_max']} local_h {c['local_hour']}",
                status="pending", order_id=coid)
        except Exception as e:
            print(f"FAILED {c['ticker']}: intent write failed ({e}) — no order sent")
            continue
        try:
            n, px, fee, order_id = _decisive_ioc(
                client, api, c["ticker"], d.side, contracts, c["q_model"],
                wc["min_edge_after_fees"],
                max_cost_usd=min(cfg_w["risk"]["max_per_trade_usd"],
                                 round(wc["daily_budget_usd"] - spent, 2)),
                client_order_id=coid)
        except OrderAmbiguous as e:
            ledger.mark_unknown(tid, f"submit ambiguous: {e}")
            print(f"CRITICAL {c['ticker']}: order outcome UNKNOWN ({e}) — "
                  f"row #{tid} frozen; reconcile resolves via fills")
            continue
        except Exception as e:
            ledger.void_trade(tid, f"pre-submit failure: {e}")
            print(f"FAILED {c['ticker']}: {e}")
            continue
        if n < 1:
            ledger.void_trade(tid, f"no fill: {px}")
            print(f"PASS  {c['ticker']}: {px}")
            continue
        cost = round(n * px + fee, 2)
        try:
            ledger.record_fill(tid, n, px, cost, fee, order_id)
            ledger.set_exit_plan(tid, "hold", 0.0, 0.0,
                                 (dt.datetime.now() + dt.timedelta(days=1)).isoformat(timespec="seconds"))
        except Exception as e:
            print(f"CRITICAL {c['ticker']}: FILLED x{n} but ledger write failed ({e}) "
                  f"— freezing #{tid} as unknown")
            try:
                ledger.mark_unknown(tid, f"filled x{n}@{px} but record_fill failed")
            except Exception:
                pass
            spent += cost
            continue
        spent += cost
        per_city[c["series"]] = per_city.get(c["series"], 0) + 1
        placed += 1
        print(f"LIVE  {c['ticker']}: {d.side.upper()} x{n} @ {px * 100:.1f}c "
              f"cost=${cost:.2f} q_model={c['q_model']:.2f} vs mkt={c['mid']:.2f} "
              f"mu={c['mu']}F sigma={c['sigma']} order={order_id}")
    print(f"done: {placed} weather orders")


def cmd_settle(_args) -> None:
    api = KalshiPublic()
    stale = ledger.void_stale_pending(60)      # OPUS-A MED: pending TTL
    if stale:
        # R3-CODEX-2 MED: say UNKNOWN (what actually happened) so the loop's
        # changed-keyword scan journals/commits this ledger mutation
        print(f"UNKNOWN: {stale} stale pending order(s) frozen (>60min, "
              f"ambiguous until reconcile)")
    settled = 0
    for t in ledger.open_trades():
        try:
            m = api.market(t["ticker"])
        except Exception as e:
            print(f"WARN  {t['ticker']}: fetch failed ({e})")
            continue
        if m.get("status") not in ("settled", "finalized"):
            continue
        res = m.get("result")
        if res in ("yes", "no"):
            win = res == t["side"]
            pnl = round(t["contracts"] - t["cost_usd"], 2) if win else round(-t["cost_usd"], 2)
            ledger.settle_trade(t["id"], res, pnl)
            settled += 1
            print(f"SETTLED {t['ticker']}: result={res} "
                  f"{'WIN' if win else 'LOSS'} pnl=${pnl:+.2f}")
        elif res in ("void", "voided", "scratch", "cancelled", "canceled"):
            # R3-CODEX-7 MED: a scratched market refunds cost — without this the
            # row sat in 'open' forever. Booked as close@pnl=0 (refund = cost back)
            # so the cash-reconciliation identity still balances (R3-FABLE HIGH).
            ledger.close_position(t["id"], 0.0, 0.0, f"market {res}: cost refunded")
            settled += 1
            print(f"VOIDED {t['ticker']}: market {res} — cost refunded, pnl $0")
        # empty/other result while finalized: settlement still publishing — wait
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


def _lane_of(ticker: str, title: str = "") -> str:
    # title-first (OPUS-A note): favorites/shortcycle share tickers, only the
    # lane tag in the title distinguishes them
    t = title or ""
    if t.startswith("favorite"):
        return "favorites"
    if t.startswith("shortcycle"):
        return "shortcycle"
    if t.startswith("weather") or ticker.startswith("KXHIGH"):
        return "weather"
    if ticker.startswith(("KXBTCD", "KXETHD", "KXSOLD", "KXXRPD")) or "15M" in ticker.split("-")[0]:
        return "shortcycle"
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

    lanes = {"shortcycle": [], "favorites": [], "weather": [], "ensemble": []}
    for t in settled_today:
        lanes[_lane_of(t["ticker"], t.get("title") or "")].append(t)
    realized = {k: round(sum(t["pnl_usd"] or 0 for t in v), 2) for k, v in lanes.items()}
    total_realized = round(sum(realized.values()), 2)

    brier = {}
    for lane in lanes:
        # R3-C1/C5 fix: favorites store q in HELD-side frame (q=price by design) —
        # scoring them as P(YES) marks winning NO favorites as huge misses. Same
        # exclusion ledger.calibration applies.
        rows = [t for t in all_settled
                if _lane_of(t["ticker"], t.get("title") or "") == lane
                and not (t.get("title") or "").startswith("favorite")]
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
    for lane in ("shortcycle", "favorites", "weather", "ensemble"):
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
    try:
        ledger.checkpoint()     # R3-CODEX-2 HIGH: fold WAL into ledger.db before the
    except Exception:           # loop's git add — the pushed backup must be current
        pass
    print(f"journal written: realized today ${total_realized:+.2f}, "
          f"{len(settled_today)} settled, {len(fills_today)} fills")


def cmd_blindai_context(_args) -> None:
    """Print ONE soon-to-settle crypto market as a blind packet (no market price)."""
    from . import blindai
    ctx = blindai.pick_context()
    if not ctx:
        print("no eligible crypto market (need one settling in 20-50 min, not yet logged)")
        return
    blindai.stash_context(ctx)
    print(json.dumps({"ticker": ctx["ticker"], "question": ctx["question"],
                      "strike": ctx["strike"], "close_time": ctx["close_time"],
                      "price_action": ctx["context"],
                      "instruction": "Estimate P(YES=settles above strike) from price action "
                                     "ONLY. Do NOT guess or reference any market/prediction "
                                     "price. Output a probability 0-1."}, ensure_ascii=False))


def cmd_blindai_record(args) -> None:
    from . import blindai
    ai = args.ai if args.ai is not None else (
        (args.claude + args.codex) / 2 if args.claude is not None and args.codex is not None
        else None)
    if ai is None:
        print("need --ai or both --claude and --codex")
        return
    blindai.record(args.ticker, ai, args.claude, args.codex)
    print(f"recorded blind call {args.ticker}: ai_yes={ai:.3f} (market fetched independently)")


def cmd_blindai_settle(_args) -> None:
    from . import blindai
    print(f"blind-AI settled: {blindai.settle()}")


def cmd_blindai_report(_args) -> None:
    from . import blindai
    print(blindai.report())


def cmd_mktsnap(_args) -> None:
    """Zero-cost calibration sampling of soon-to-settle crypto markets (H5)."""
    from .mktcal import snapshot
    added, resolved = snapshot()
    print(f"mktsnap: {added} quotes recorded, {resolved} outcomes resolved")


def cmd_mktcal(_args) -> None:
    from .mktcal import report
    print(report())


def cmd_reconcile(_args) -> None:
    """Ledger-vs-exchange position reconciliation — the accounting truth test.
    Compares net exchange positions against ledger open trades; any mismatch means
    a booking bug (phantom close, unrecorded fill, wrong side) and prints loudly."""
    cfg = load_config()
    if not live_active(cfg):
        print("reconcile requires live mode")
        return
    from .live import KalshiLive, LiveAuthError
    try:
        client = KalshiLive()
        pos = client.positions()
    except LiveAuthError as e:
        print(f"AUTH ERROR: {e}")
        return
    exch = {}
    for p in pos.get("market_positions") or []:
        # R3-CODEX-7 HIGH: accept BOTH field shapes — position_fp (fp string) and
        # position (int) — a shape change must never blank the safety net
        raw = p.get("position_fp")
        if raw is None:
            raw = p.get("position")
        net = float(raw or 0)
        if abs(net) > 1e-9:
            exch[p["ticker"]] = net                 # +N = long yes, -N = long no
    # ---- unknown resolver (R3-CODEX-7: 'unknown' must not be an absorbing state) --
    con_r = ledger._conn()
    unknowns = [dict(r) for r in con_r.execute(
        "SELECT id, ts, ticker, side, contracts, price, order_id FROM trades "
        "WHERE status='unknown'")]
    for u in unknowns:
        oid = (u.get("order_id") or "").strip()
        resolved = False
        if oid and oid != "?":
            try:
                # R4-FABLE-A CRITICAL fix: fills do NOT carry client_order_id — map
                # our client id to the EXCHANGE order via /portfolio/orders first;
                # only an authoritative empty lookup may 2h-void a frozen row.
                ords = client.orders(ticker=u["ticker"])
                mine_ord = [o for o in ords
                            if oid in (str(o.get("client_order_id") or ""),
                                       str(o.get("order_id") or ""))]
                if not mine_ord:
                    age_h = (dt.datetime.now()
                             - dt.datetime.fromisoformat(u["ts"])).total_seconds() / 3600
                    if age_h >= 2:        # by-id lookup succeeded, empty, aged:
                        ledger.void_trade(u["id"], "no exchange order matches the "
                                                   "client id after 2h — never accepted")
                        print(f"RESOLVED #{u['id']} {u['ticker']}: no order -> voided")
                        resolved = True
                else:
                    o = mine_ord[0]
                    exch_oid = str(o.get("order_id") or "")
                    fl = client.fills(ticker=u["ticker"], limit=100).get("fills") or []
                    mine = [f for f in fl if str(f.get("order_id") or "") == exch_oid]
                    cnt = sum(float(f.get("count_fp") or f.get("count") or 0)
                              for f in mine)
                    n = int(round(cnt))
                    if n >= 1:
                        tot = 0.0
                        for f in mine:
                            ci = float(f.get("count_fp") or f.get("count") or 0)
                            # R4-FABLE-A HIGH fix: 2026 payload = *_dollars fields;
                            # read the HELD side directly (no conversion error), and
                            # the cents fallback treats >=1 as cents (1c boundary)
                            if u["side"] == "no":
                                raw = f.get("no_price_dollars")
                                if raw is not None:
                                    pi = float(raw)
                                else:
                                    yp = float(f.get("yes_price") or 0)
                                    pi = 1.0 - (yp / 100.0 if yp >= 1 else yp)
                            else:
                                raw = f.get("yes_price_dollars")
                                if raw is not None:
                                    pi = float(raw)
                                else:
                                    yp = float(f.get("yes_price") or 0)
                                    pi = yp / 100.0 if yp >= 1 else yp
                            tot += ci * pi
                        avg = round(tot / cnt, 4) if cnt else u["price"]
                        fee = taker_fee_usd(avg, n)
                        ledger.record_fill(u["id"], n, avg, round(n * avg + fee, 2),
                                           fee, exch_oid)
                        print(f"RESOLVED #{u['id']} {u['ticker']}: fills prove x{n} "
                              f"@ {avg * 100:.0f}c -> open")
                        resolved = True
                    elif str(o.get("status") or "") in ("canceled", "cancelled",
                                                        "expired", "rejected"):
                        ledger.void_trade(u["id"], f"exchange order "
                                                   f"{o.get('status')} with zero fills")
                        print(f"RESOLVED #{u['id']} {u['ticker']}: order "
                              f"{o.get('status')}, no fills -> voided")
                        resolved = True
                    # order exists in another state with no visible fills: keep
                    # frozen — never guess against a live order
            except Exception as e:
                print(f"WARN resolver #{u['id']}: {e}")
        if not resolved:
            print(f"UNKNOWN #{u['id']} {u['ticker']} {u['side']} x{u['contracts']} "
                  f"-> unresolved (ambiguous exchange state)")
    led = {}
    for t in ledger.open_trades():                    # AFTER resolver: fresh statuses
        if t["mode"] != "live":
            continue
        net = t["contracts"] if t["side"] == "yes" else -t["contracts"]
        led[t["ticker"]] = led.get(t["ticker"], 0) + net
    problems = 0
    for tk in sorted(set(exch) | set(led)):
        e, l = exch.get(tk, 0), led.get(tk, 0)
        if abs(e - l) > 1e-9:
            problems += 1
            print(f"MISMATCH {tk}: exchange={e:+.0f} ledger={l:+.0f}"
                  f"  <- {'exchange has untracked position' if abs(e) > abs(l) else 'ledger claims more than exchange holds'}")
        else:
            print(f"OK       {tk}: {e:+.0f}")
    # ---- cash reconciliation (R3-FABLE HIGH): contracts-only compare is blind to
    # booking-PRICE corruption. Identity: balance_now - balance_prev must equal
    # (returned cash: cost+pnl of rows settled/closed since) - (consumed cash:
    # cost of rows entered since). Alert on > $1 drift (deposits also trip once).
    problems_cash = 0
    try:
        bal_now = float(client.balance().get("balance_dollars") or 0)
        snap_path = Path("data") / "cash_check.json"
        now_iso = dt.datetime.now().isoformat(timespec="seconds")
        if snap_path.exists():
            prev = json.loads(snap_path.read_text(encoding="utf-8"))
            returned = con_r.execute(
                "SELECT COALESCE(SUM(cost_usd + COALESCE(pnl_usd,0)),0) FROM trades "
                "WHERE mode='live' AND status IN ('settled','closed') AND settled_ts > ?",
                (prev["ts"],)).fetchone()[0]
            consumed = con_r.execute(
                # R4-FABLE-A MED fix: key on when cash MOVED (booked_ts), not on
                # decide-time ts — a pending confirmed hours later was never counted
                "SELECT COALESCE(SUM(cost_usd),0) FROM trades WHERE mode='live' "
                "AND COALESCE(booked_ts, ts) > ? "
                "AND status IN ('open','closed','settled','unknown')",
                (prev["ts"],)).fetchone()[0]
            expected = prev["balance"] + returned - consumed
            drift = bal_now - expected
            if abs(drift) > 1.0:
                problems_cash = 1
                print(f"CASH MISMATCH: balance ${bal_now:.2f} vs expected "
                      f"${expected:.2f} (drift ${drift:+.2f}) — booking corruption "
                      f"or external deposit/withdrawal")
            else:
                print(f"CASH OK: balance ${bal_now:.2f} ~ expected ${expected:.2f} "
                      f"(drift ${drift:+.2f})")
        snap_path.write_text(json.dumps({"ts": now_iso, "balance": bal_now}),
                             encoding="utf-8")
    except Exception as e:
        print(f"WARN cash check failed: {e}")
    problems += problems_cash
    print(f"reconcile: {len(set(exch) | set(led))} tickers, {problems} mismatches"
          + (" — ACCOUNTING CLEAN" if problems == 0 else " — INVESTIGATE"))


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
    cfg_x = _live_risk_overlay(cfg)
    for t in rows:
        # R3-CODEX-6 HIGH fix: a pending decision may be STALE — resident lanes can
        # spend the cap room between decide and execute. Re-check caps now. The
        # row's dollars are already inside stats (additional cost 0) and its slot
        # is its own, so exclude it from the position count (R4-FABLE-A MED: at
        # the cap boundary the row otherwise vetoes ITSELF forever).
        st_x = ledger.stats("live")
        st_x["open_positions"] = max(0, st_x["open_positions"] - 1)
        veto = engine.check_risk(st_x, 0.0, cfg_x)
        if veto:
            failed += 1
            print(f"VETO #{t['id']} {t['ticker']}: {veto} (stays pending)")
            continue
        # R4-FABLE-A HIGH fix: mint the order identity BEFORE the POST — without
        # it an ambiguous submit freezes a row the resolver can never look up.
        coid = (t.get("order_id") or "").strip() or str(uuid.uuid4())
        try:
            ledger.set_client_oid(t["id"], coid)
        except Exception as e:
            failed += 1
            print(f"FAILED #{t['id']} {t['ticker']}: identity write failed ({e}) "
                  f"— no order sent")
            continue
        try:
            resp = client.place_limit(t["ticker"], t["side"], t["contracts"], t["price"],
                                      client_order_id=coid)
        except RuntimeError as e:
            failed += 1
            st = _http_status(e)
            if st is not None and 400 <= st < 500:   # provable reject: no order
                try:                       # clear identity so the TTL VOIDS (not
                    ledger.set_client_oid(t["id"], None)   # freezes) this row later
                except Exception:
                    pass
                print(f"REJECTED #{t['id']} {t['ticker']}: {str(e)[:90]} (stays pending)")
            else:                          # R3 consensus CRITICAL: 5xx may have filled
                ledger.mark_unknown(t["id"], f"submit ambiguous: {str(e)[:100]}")
                print(f"UNKNOWN #{t['id']} {t['ticker']}: submit ambiguous ({str(e)[:70]}) "
                      f"— frozen; reconcile resolves via orders/fills")
            continue
        except Exception as e:             # timeout/connection: POST may have landed
            failed += 1
            ledger.mark_unknown(t["id"], f"submit ambiguous: {type(e).__name__} {str(e)[:80]}")
            print(f"UNKNOWN #{t['id']} {t['ticker']}: {type(e).__name__} — frozen; "
                  f"reconcile resolves via orders/fills")
            continue
        try:
            order_id = (resp.get("order") or {}).get("order_id") or resp.get("order_id") or "?"
            # OPUS-A CRITICAL fix: an IOC can return 200 with zero fills — never book
            # a phantom. Parse fills; 0 -> cancel stray + stay pending.
            fill_raw = float(resp.get("fill_count") or resp.get("fill_count_fp") or 0)
            filled = int(fill_raw)
            if abs(fill_raw - filled) > 1e-9:      # R3-CODEX-3: fractional fill
                ledger.mark_unknown(t["id"], f"fractional fill_count {fill_raw}")
                failed += 1
                print(f"UNKNOWN #{t['id']} {t['ticker']}: fractional fill {fill_raw} — frozen")
                continue
            if filled < 1:
                if order_id != "?":
                    try:
                        client.cancel_order(str(order_id))
                    except Exception:
                        pass
                try:                       # provably flat: clear identity so the
                    ledger.set_client_oid(t["id"], None)   # TTL voids, not freezes
                except Exception:
                    pass
                failed += 1
                print(f"NOFILL #{t['id']} {t['ticker']}: stays pending (book moved)")
                continue
            # CODEX-1/2 fixes: ALWAYS book the actual average (full fills too);
            # frame-convert only exchange-reported averages; single atomic write
            # (record_fill) closes the resize->mark crash window.
            raw_avg = resp.get("average_fill_price")
            if raw_avg is not None and str(raw_avg) != "":
                avg_px = float(raw_avg)
                if t["side"] == "no":
                    avg_px = round(1.0 - avg_px, 4)
            else:
                avg_px = t["price"]
            fee_paid = float(resp.get("average_fee_paid") or 0) * filled
            fee = round(fee_paid, 2) if fee_paid else taker_fee_usd(avg_px, filled)
            try:
                ledger.record_fill(t["id"], filled, avg_px,
                                   round(filled * avg_px + fee, 2), fee, str(order_id))
            except Exception as e:
                print(f"CRITICAL #{t['id']} {t['ticker']}: FILLED ON EXCHANGE but ledger "
                      f"write failed ({e}) -> marking unknown; reconcile will flag")
                try:
                    ledger.mark_unknown(t["id"], f"filled x{filled} but record failed")
                except Exception:
                    pass
                failed += 1
                continue
            # R3-CODEX-1 MED fix: exit plan must track the ACTUAL entry, not the
            # pre-submit quote (a 13c fill with 10c-based stops exits at wrong levels)
            try:
                _assign_exit_plan(t["id"], t["side"], avg_px, t["q_consensus"] or 0, cfg)
            except Exception:
                pass                       # plan refresh is best-effort; fill is booked
            ok += 1
            print(f"PLACED #{t['id']} {t['ticker']} {t['side'].upper()} x{filled} "
                  f"@ {avg_px * 100:.1f}c order_id={order_id}")
        except Exception as e:             # response in hand but handling broke:
            failed += 1                    # state unproven -> freeze, never retry
            print(f"CRITICAL #{t['id']} {t['ticker']}: response handling failed ({e}) "
                  f"-> marking unknown")
            try:
                ledger.mark_unknown(t["id"], f"response handling failed: {str(e)[:80]}")
            except Exception:
                pass
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
    sub.add_parser("favorites").set_defaults(fn=cmd_favorites)
    sub.add_parser("journal").set_defaults(fn=cmd_journal)
    sub.add_parser("mktsnap").set_defaults(fn=cmd_mktsnap)
    sub.add_parser("mktcal").set_defaults(fn=cmd_mktcal)
    sub.add_parser("blindai-context").set_defaults(fn=cmd_blindai_context)
    p = sub.add_parser("blindai-record")
    p.add_argument("--ticker", required=True)
    p.add_argument("--ai", type=float, default=None)
    p.add_argument("--claude", type=float, default=None)
    p.add_argument("--codex", type=float, default=None)
    p.set_defaults(fn=cmd_blindai_record)
    sub.add_parser("blindai-settle").set_defaults(fn=cmd_blindai_settle)
    sub.add_parser("blindai-report").set_defaults(fn=cmd_blindai_report)
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
    sub.add_parser("reconcile").set_defaults(fn=cmd_reconcile)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
