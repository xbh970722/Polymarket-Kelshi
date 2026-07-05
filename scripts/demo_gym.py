"""Kalshi demo OMS torture gym.

This script is intentionally self-contained: it uses only KalshiLive(demo=True),
does not import ledger, and writes exactly one result file under data/.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.live import API, KalshiLive  # noqa: E402


RESULTS_PATH = ROOT / "data" / "demo_gym_results.json"
RUN_ID = f"dg{uuid.uuid4().hex[:8]}"
ORDER_PREFIX = f"{RUN_ID}-"
ACTIVE_STATUSES = {
    "open",
    "opened",
    "resting",
    "pending",
    "partially_filled",
    "initialized",
    "accepted",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def short(obj, n: int = 700) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=True, sort_keys=True)
    except TypeError:
        text = str(obj)
    return text[:n]


def fnum(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def api_error(exc: BaseException) -> dict:
    text = str(exc)
    return {
        "type": exc.__class__.__name__,
        "message": text[:900],
        "is_429": "HTTP 429" in text,
        "is_4xx": any(f"HTTP {code}" in text for code in range(400, 500)),
    }


def is_not_found_error(err: dict) -> bool:
    return err.get("is_4xx") and "not_found" in str(err.get("message") or "")


def result(status: str, evidence: str, **fields) -> dict:
    out = {"status": status, "evidence": evidence}
    out.update(fields)
    return out


def emit(label: str, row: dict) -> None:
    print(f"{label} {row['status']} | {row['evidence']}", flush=True)


def normalize_market(raw: dict) -> dict:
    return {
        "ticker": raw.get("ticker"),
        "status": raw.get("status"),
        "title": raw.get("title") or "",
        "event_ticker": raw.get("event_ticker"),
        "yes_bid": fnum(raw.get("yes_bid_dollars")),
        "yes_ask": fnum(raw.get("yes_ask_dollars")),
        "no_bid": fnum(raw.get("no_bid_dollars")),
        "no_ask": fnum(raw.get("no_ask_dollars")),
        "yes_bid_size": fnum(raw.get("yes_bid_size_fp") or raw.get("yes_bid_size")),
        "yes_ask_size": fnum(raw.get("yes_ask_size_fp") or raw.get("yes_ask_size")),
        "no_bid_size": fnum(raw.get("no_bid_size_fp") or raw.get("no_bid_size")),
        "no_ask_size": fnum(raw.get("no_ask_size_fp") or raw.get("no_ask_size")),
        "close_time": raw.get("close_time"),
        "raw": raw,
    }


def market_priority(m: dict) -> tuple:
    text = f"{m.get('ticker') or ''} {m.get('title') or ''}".upper()
    domain = 0 if any(k in text for k in ("ESPORT", "MLB", "GAME")) else 1
    spread = max(0.0, m["yes_ask"] - m["yes_bid"])
    return (domain, spread, m["yes_ask"], m.get("ticker") or "")


def fetch_markets(client: KalshiLive, max_pages: int = 4) -> list[dict]:
    out: list[dict] = []
    cursor = None
    for _ in range(max_pages):
        params = {"status": "open", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        page = client._req("GET", f"{API}/markets", params=params)
        out.extend(normalize_market(m) for m in (page.get("markets") or []))
        cursor = page.get("cursor")
        if not cursor:
            break
    return out


def fetch_market(client: KalshiLive, ticker: str) -> dict | None:
    try:
        page = client._req("GET", f"{API}/markets/{ticker}")
        raw = page.get("market") or page
        return normalize_market(raw)
    except Exception:
        return None


def order_id_from(resp: dict | None) -> str | None:
    if not isinstance(resp, dict):
        return None
    if resp.get("order_id"):
        return str(resp["order_id"])
    for key in ("order", "order_info", "order_response"):
        val = resp.get(key)
        if isinstance(val, dict) and val.get("order_id"):
            return str(val["order_id"])
    return None


def order_from(resp: dict | None) -> dict | None:
    if not isinstance(resp, dict):
        return None
    if resp.get("order_id"):
        return resp
    for key in ("order", "order_info", "order_response"):
        val = resp.get(key)
        if isinstance(val, dict):
            return val
    return None


def is_active_order(order: dict | None) -> bool:
    if not order:
        return False
    status = str(order.get("status") or "").lower()
    remaining = fnum(order.get("remaining_count_fp") or order.get("remaining_count"))
    return status in ACTIVE_STATUSES or remaining > 1e-9


def find_order(
    client: KalshiLive,
    ticker: str | None = None,
    order_id: str | None = None,
    client_order_id: str | None = None,
    tries: int = 5,
    delay: float = 0.35,
) -> dict | None:
    for i in range(tries):
        try:
            for order in client.orders(ticker=ticker, limit=100):
                if order_id and str(order.get("order_id") or "") == str(order_id):
                    return order
                if client_order_id and str(order.get("client_order_id") or "") == client_order_id:
                    return order
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(delay)
    return None


def fill_count(order: dict | None) -> float:
    if not order:
        return 0.0
    return fnum(
        order.get("fill_count_fp")
        or order.get("filled_count_fp")
        or order.get("fill_count")
        or order.get("filled_count")
    )


def remaining_count(order: dict | None) -> float:
    if not order:
        return 0.0
    return fnum(order.get("remaining_count_fp") or order.get("remaining_count"))


def position_net_map(pos: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in pos.get("market_positions") or []:
        ticker = p.get("ticker")
        if not ticker:
            continue
        raw = p.get("position_fp")
        if raw is None:
            raw = p.get("position")
        net = round(fnum(raw), 4)
        if abs(net) > 1e-9:
            out[str(ticker)] = net
    return out


def choose_rest_params(m: dict) -> tuple[str, float]:
    candidates: list[tuple[str, float]] = []
    if m["yes_ask"] > 0.0015:
        candidates.append(("yes", m["yes_ask"]))
    if m["no_ask"] > 0.0015:
        candidates.append(("no", m["no_ask"]))
    if not candidates:
        return "yes", 0.0001
    side, ask = max(candidates, key=lambda x: x[1])
    price = min(0.01, max(0.001, ask / 4.0))
    if price >= ask:
        price = max(0.0001, ask - 0.001)
    return side, round(price, 4)


def side_quote(m: dict, side: str) -> dict:
    if side == "yes":
        return {
            "side": "yes",
            "entry_ask": m["yes_ask"],
            "entry_size": m["yes_ask_size"],
            "exit_bid": m["yes_bid"],
            "exit_size": m["yes_bid_size"],
        }
    return {
        "side": "no",
        "entry_ask": m["no_ask"],
        "entry_size": m["no_ask_size"],
        "exit_bid": m["no_bid"],
        "exit_size": m["no_bid_size"],
    }


def discover(client: KalshiLive, baseline: dict[str, float]) -> dict:
    active_order_tickers = set()
    try:
        for order in client.orders(limit=100):
            if is_active_order(order):
                active_order_tickers.add(str(order.get("ticker") or ""))
    except Exception:
        active_order_tickers = set()

    markets = [
        m for m in fetch_markets(client)
        if m["status"] == "active"
        and m.get("ticker")
        and m["ticker"] not in baseline
        and m["ticker"] not in active_order_tickers
    ]
    markets.sort(key=market_priority)
    rest = None
    for m in markets:
        if m["yes_ask"] > 0.0015 or m["no_ask"] > 0.0015:
            rest = m
            break

    live_sides = []
    capped_sides = []
    for m in markets:
        for side in ("yes", "no"):
            q = side_quote(m, side)
            spread_ok = 0.0 < q["exit_bid"] < q["entry_ask"] < 1.0
            size_ok = q["entry_size"] > 0 and q["exit_size"] > 0
            if spread_ok and size_ok:
                item = {"market": m, **q}
                live_sides.append(item)
                if q["entry_ask"] <= 0.60:
                    capped_sides.append(item)

    live_sides.sort(
        key=lambda x: (
            market_priority(x["market"]),
            max(1.0, x["entry_size"]),
            x["entry_ask"],
        )
    )
    capped_sides.sort(
        key=lambda x: (
            market_priority(x["market"]),
            max(1.0, x["entry_size"]),
            x["entry_ask"],
        )
    )
    return {
        "rest": rest,
        "live": live_sides[0] if live_sides else None,
        "capped": capped_sides[0] if capped_sides else None,
        "live_candidates": live_sides,
        "capped_candidates": capped_sides,
        "market_count": len(markets),
        "active_order_tickers": sorted(t for t in active_order_tickers if t),
    }


class Gym:
    def __init__(self, client: KalshiLive):
        self.client = client
        self.baseline_positions = position_net_map(client.positions())
        self.touched_tickers: set[str] = set()
        self.cleanup_errors: list[dict] = []
        self.discovery = discover(client, self.baseline_positions)

    def coid(self, tag: str) -> str:
        return f"{ORDER_PREFIX}{tag}-{uuid.uuid4().hex[:6]}"

    def place(
        self,
        ticker: str,
        side: str,
        count: int,
        price: float,
        tif: str,
        tag: str,
        expiration_ts: int | None = None,
        client_order_id: str | None = None,
    ) -> tuple[dict, dict | None]:
        self.touched_tickers.add(ticker)
        coid = client_order_id or self.coid(tag)
        resp = self.client.place_limit(
            ticker,
            side,
            count,
            price,
            tif=tif,
            client_order_id=coid,
            expiration_ts=expiration_ts,
        )
        order = order_from(resp)
        oid = order_id_from(resp)
        if not order:
            order = find_order(self.client, ticker=ticker, order_id=oid, client_order_id=coid)
        if order:
            order["_gym_client_order_id"] = coid
        else:
            order = {"client_order_id": coid, "order_id": oid}
        return resp, order

    def cancel_if_active(self, order: dict | None) -> dict:
        if not order:
            return {"skipped": "no order"}
        oid = order.get("order_id")
        ticker = order.get("ticker")
        fresh = None
        try:
            fresh = find_order(
                self.client,
                ticker=ticker,
                order_id=str(oid) if oid else None,
                client_order_id=order.get("_gym_client_order_id") or order.get("client_order_id"),
                tries=2,
                delay=0.15,
            )
        except Exception:
            fresh = order
        if not is_active_order(fresh or order):
            return {"skipped": "not active", "order": fresh or order}
        try:
            return self.client.cancel_order(str(oid))
        except Exception as exc:
            err = api_error(exc)
            if not is_not_found_error(err):
                self.cleanup_errors.append({"cancel": str(oid), "error": err})
            return {"error": err}

    def cleanup_orders(self) -> None:
        try:
            orders = self.client.orders(limit=100)
        except Exception as exc:
            self.cleanup_errors.append({"orders_lookup": api_error(exc)})
            return
        for order in orders:
            coid = str(order.get("client_order_id") or "")
            if coid.startswith(ORDER_PREFIX) and is_active_order(order):
                try:
                    self.client.cancel_order(str(order.get("order_id")))
                except Exception as exc:
                    err = api_error(exc)
                    if not is_not_found_error(err):
                        self.cleanup_errors.append(
                            {"cancel_prefix": order.get("order_id"), "error": err}
                        )

    def flatten_positions(self, attempts: int = 3) -> None:
        for _ in range(attempts):
            current = position_net_map(self.client.positions())
            deltas = []
            for ticker in self.touched_tickers:
                delta = round(current.get(ticker, 0.0) - self.baseline_positions.get(ticker, 0.0), 4)
                if abs(delta) > 1e-6:
                    deltas.append((ticker, delta))
            if not deltas:
                return
            for ticker, delta in deltas:
                m = fetch_market(self.client, ticker)
                if not m:
                    self.cleanup_errors.append({"flatten": ticker, "error": "market fetch failed"})
                    continue
                side = "yes" if delta > 0 else "no"
                count = int(round(abs(delta)))
                if count <= 0 or abs(abs(delta) - count) > 1e-6:
                    self.cleanup_errors.append(
                        {"flatten": ticker, "error": f"fractional/unrounded delta {delta}"}
                    )
                    continue
                price = m["yes_bid"] if side == "yes" else m["no_bid"]
                if price <= 0:
                    self.cleanup_errors.append(
                        {"flatten": ticker, "side": side, "error": "no exit bid"}
                    )
                    continue
                try:
                    self.client.place_exit(ticker, side, count, min(max(price, 0.0001), 0.9999))
                except Exception as exc:
                    self.cleanup_errors.append(
                        {"flatten": ticker, "side": side, "count": count, "error": api_error(exc)}
                    )
            time.sleep(1.0)

    def cleanup(self) -> None:
        self.cleanup_orders()
        self.flatten_positions()

    def positions_match_baseline(self) -> tuple[bool, dict[str, float]]:
        current = position_net_map(self.client.positions())
        return current == self.baseline_positions, current


def parse_expiry(order: dict | None) -> tuple[bool, dict]:
    if not order:
        return False, {}
    fields = {}
    for key, value in order.items():
        lk = str(key).lower()
        if "expiration" in lk or "expiry" in lk:
            fields[key] = value
    return bool(fields), fields


def test_t1(g: Gym) -> dict:
    m = g.discovery["rest"]
    if not m:
        return result("SKIP", "no active market available for resting expiration order")
    ticker = m["ticker"]
    side, price = choose_rest_params(m)
    coid = g.coid("T1")
    exp = int(time.time()) + 120
    order = None
    try:
        resp, order = g.place(
            ticker, side, 1, price, "good_till_canceled", "T1", expiration_ts=exp,
            client_order_id=coid,
        )
        oid = order.get("order_id")
        seen = find_order(g.client, ticker=ticker, order_id=oid, client_order_id=coid)
        echo_present, echo_fields = parse_expiry(seen or order)
        active_before = is_active_order(seen or order)
        time.sleep(130)
        after = find_order(g.client, ticker=ticker, order_id=oid, client_order_id=coid, tries=3)
        expired = not is_active_order(after)
        if after and is_active_order(after):
            g.cancel_if_active(after)
        status = "PASS" if active_before and expired and echo_present else "FAIL"
        evidence = (
            f"{ticker} {side}@{price:.4f}; active_before={active_before}; "
            f"expiry_echo={bool(echo_fields)}; after_status={(after or {}).get('status')}; "
            f"auto_inactive={expired}"
        )
        return result(
            status,
            evidence,
            ticker=ticker,
            side=side,
            price=price,
            expiration_ts=exp,
            order_id=oid,
            place_response=short(resp),
            readback_order=short(seen),
            expiry_fields=echo_fields,
            after_order=short(after),
        )
    except Exception as exc:
        return result("FAIL", f"exception during expiration roundtrip: {api_error(exc)['message']}", error=api_error(exc))
    finally:
        g.cleanup()


def test_t2(g: Gym) -> dict:
    m = g.discovery["rest"]
    if not m:
        return result("SKIP", "no active market available for GTC lifecycle")
    ticker = m["ticker"]
    side, price = choose_rest_params(m)
    coid = g.coid("T2")
    try:
        resp, order = g.place(ticker, side, 1, price, "good_till_canceled", "T2", client_order_id=coid)
        oid = order.get("order_id")
        seen = find_order(g.client, ticker=ticker, order_id=oid, client_order_id=coid)
        active_before = is_active_order(seen or order)
        cancel_resp = g.client.cancel_order(str(oid))
        after_cancel = find_order(g.client, ticker=ticker, order_id=oid, client_order_id=coid)
        cancel_ack = fnum(cancel_resp.get("reduced_by")) > 0 or str(cancel_resp.get("order_id") or "") == str(oid)
        canceled = (
            cancel_ack
            or str((after_cancel or {}).get("status") or "").lower() == "canceled"
            or not is_active_order(after_cancel)
        )
        second = None
        second_ok = False
        try:
            second = g.client.cancel_order(str(oid))
            second_order = order_from(second)
            second_status = str((second_order or second or {}).get("status") or "").lower()
            second_ok = second_status == "canceled"
        except Exception as exc:
            second = {"error": api_error(exc)}
            second_ok = second["error"]["is_4xx"]
        status = "PASS" if active_before and canceled and second_ok else "FAIL"
        evidence = (
            f"{ticker} order={oid}; visible={active_before}; cancel_ack={cancel_ack}; "
            f"orders_readback_status={(after_cancel or {}).get('status')}; "
            f"second_cancel={short(second, 180)}"
        )
        return result(
            status,
            evidence,
            ticker=ticker,
            side=side,
            price=price,
            order_id=oid,
            place_response=short(resp),
            cancel_response=short(cancel_resp),
            after_cancel=short(after_cancel),
            cancel_ack=cancel_ack,
            second_cancel=second,
        )
    except Exception as exc:
        return result("FAIL", f"exception during GTC lifecycle: {api_error(exc)['message']}", error=api_error(exc))
    finally:
        g.cleanup()


def refreshed_side(g: Gym, side_info: dict | None, cap: float | None = None) -> dict | None:
    if not side_info:
        return None
    m = fetch_market(g.client, side_info["market"]["ticker"])
    if not m or m["status"] != "active":
        return None
    q = side_quote(m, side_info["side"])
    if not (0.0 < q["exit_bid"] < q["entry_ask"] < 1.0):
        return None
    if q["entry_size"] <= 0 or q["exit_size"] <= 0:
        return None
    if cap is not None and q["entry_ask"] > cap:
        return None
    return {"market": m, **q}


def test_t3(g: Gym) -> dict:
    if not g.discovery["live"]:
        return result("SKIP", "no active livebook market; fill-required cancel race skipped")
    stats = {"fill_before_cancel": 0, "cancel_won": 0, "unknown": 0}
    attempts = []
    try:
        for i in range(10):
            live = refreshed_side(g, g.discovery["live"])
            if not live:
                attempts.append({"i": i + 1, "classification": "unknown", "error": "live quote vanished"})
                stats["unknown"] += 1
                continue
            ticker = live["market"]["ticker"]
            side = live["side"]
            price = min(max(live["entry_ask"], 0.0001), 0.9999)
            coid = g.coid(f"T3-{i+1}")
            placed = None
            cancel_resp = None
            err = None
            try:
                resp, placed = g.place(
                    ticker, side, 1, price, "good_till_canceled", f"T3-{i+1}",
                    client_order_id=coid,
                )
                oid = placed.get("order_id")
                try:
                    cancel_resp = g.client.cancel_order(str(oid))
                except Exception as exc:
                    cancel_resp = {"error": api_error(exc)}
                final = find_order(g.client, ticker=ticker, order_id=oid, client_order_id=coid)
                filled = fill_count(final or placed)
                if filled > 0:
                    cls = "fill_before_cancel"
                elif str((final or {}).get("status") or "").lower() == "canceled":
                    cls = "cancel_won"
                else:
                    cls = "unknown"
                stats[cls] += 1
                attempts.append(
                    {
                        "i": i + 1,
                        "ticker": ticker,
                        "side": side,
                        "price": price,
                        "order_id": oid,
                        "classification": cls,
                        "fill_count": filled,
                        "final_status": (final or {}).get("status"),
                        "cancel": short(cancel_resp, 250),
                        "place": short(resp, 250),
                    }
                )
            except Exception as exc:
                err = api_error(exc)
                stats["unknown"] += 1
                attempts.append({"i": i + 1, "classification": "unknown", "error": err})
            finally:
                g.cleanup()
                time.sleep(0.25)
        status = "PASS" if len(attempts) == 10 and stats["unknown"] == 0 else "FAIL"
        evidence = (
            f"10 races; fill_before_cancel={stats['fill_before_cancel']}, "
            f"cancel_won={stats['cancel_won']}, unknown={stats['unknown']}"
        )
        return result(status, evidence, stats=stats, attempts=attempts)
    finally:
        g.cleanup()


def exit_filled_position(g: Gym, ticker: str, side: str, count: int) -> dict:
    m = fetch_market(g.client, ticker)
    if not m:
        return {"error": "market fetch failed"}
    price = m["yes_bid"] if side == "yes" else m["no_bid"]
    if price <= 0:
        return {"error": "no exit bid", "side": side, "market": short(m, 300)}
    try:
        return g.client.place_exit(ticker, side, count, min(max(price, 0.0001), 0.9999))
    except Exception as exc:
        return {"error": api_error(exc)}


def test_t4(g: Gym) -> dict:
    if not g.discovery["live"]:
        return result("SKIP", "no active livebook market; fills-to-cash replay skipped")
    capped = refreshed_side(g, g.discovery["capped"], cap=0.60)
    if not capped:
        return result("SKIP", "no live side with entry limit <=0.60 for 999-lot IOC replay")
    ticker = capped["market"]["ticker"]
    side = capped["side"]
    price = min(capped["entry_ask"], 0.60)
    coid = g.coid("T4")
    try:
        resp, placed = g.place(
            ticker, side, 999, price, "immediate_or_cancel", "T4", client_order_id=coid
        )
        oid = placed.get("order_id")
        final = find_order(g.client, ticker=ticker, order_id=oid, client_order_id=coid)
        order = final or placed
        filled = fill_count(order)
        remaining = remaining_count(order)
        fp = str((order or {}).get("fill_count_fp") or "")
        has_decimal_point = "." in fp
        fractional_nonzero = False
        if "." in fp:
            fractional_nonzero = any(ch != "0" for ch in fp.split(".", 1)[1])
        exit_resp = None
        if filled > 0:
            exit_resp = exit_filled_position(g, ticker, side, int(math.ceil(filled)))
            time.sleep(1.0)
        g.cleanup()
        partial = 0 < filled < 999 and not is_active_order(order)
        clean, current = g.positions_match_baseline()
        status = "PASS" if partial and clean else "FAIL"
        evidence = (
            f"{ticker} {side} 999@{price:.4f}; fill_count_fp={fp or filled}; "
            f"remaining={remaining}; status={(order or {}).get('status')}; clean={clean}"
        )
        return result(
            status,
            evidence,
            ticker=ticker,
            side=side,
            limit_price=price,
            order_id=oid,
            fill_count=filled,
            fill_count_fp=fp,
            fill_count_has_decimal_point=has_decimal_point,
            fill_count_fractional_nonzero=fractional_nonzero,
            remaining=remaining,
            place_response=short(resp),
            final_order=short(order),
            exit_response=short(exit_resp),
            positions_after=current,
        )
    except Exception as exc:
        return result("FAIL", f"exception during 999-lot replay: {api_error(exc)['message']}", error=api_error(exc))
    finally:
        g.cleanup()


def test_t5(g: Gym) -> dict:
    if not g.discovery["live"]:
        return result("SKIP", "no active livebook market; no-hold/over-exit reduce_only boundary skipped")
    live = refreshed_side(g, g.discovery["live"])
    if not live:
        return result("SKIP", "live quote vanished before reduce_only boundary")
    no_hold_ticker = live["market"]["ticker"]
    no_hold_side = live["side"]
    no_hold = None
    over_exit = None
    entry_attempts = []
    try:
        g.touched_tickers.add(no_hold_ticker)
        try:
            no_hold = g.client.place_exit(no_hold_ticker, no_hold_side, 1, live["exit_bid"])
        except Exception as exc:
            no_hold = {"error": api_error(exc)}
        g.cleanup()
        no_hold_order = order_from(no_hold) if isinstance(no_hold, dict) else None
        no_hold_fill = fill_count(no_hold_order or no_hold)
        no_hold_ok = bool((isinstance(no_hold, dict) and no_hold.get("error", {}).get("is_4xx")) or no_hold_fill == 0)

        current_discovery = discover(g.client, g.baseline_positions)
        candidates = current_discovery.get("live_candidates") or []
        if not candidates:
            over_exit = {"skip": "no live candidates after no-hold probe"}
            status = "SKIP" if no_hold_ok else "FAIL"
        for idx, candidate in enumerate(candidates[:6], start=1):
            if over_exit is not None:
                break
            live_entry = refreshed_side(g, candidate)
            if not live_entry:
                entry_attempts.append({"i": idx, "skip": "quote vanished"})
                continue
            ticker = live_entry["market"]["ticker"]
            side = live_entry["side"]
            try:
                buy_resp, buy_order = g.place(
                    ticker,
                    side,
                    1,
                    live_entry["entry_ask"],
                    "immediate_or_cancel",
                    f"T5-buy-{idx}",
                )
            except Exception as exc:
                entry_attempts.append({"i": idx, "ticker": ticker, "side": side, "error": api_error(exc)})
                g.cleanup()
                continue
            buy_final = find_order(g.client, ticker=ticker, order_id=buy_order.get("order_id"))
            bought = fill_count(buy_final or buy_order)
            if bought <= 0:
                entry_attempts.append(
                    {
                        "i": idx,
                        "ticker": ticker,
                        "side": side,
                        "entry_ask": live_entry["entry_ask"],
                        "fill": bought,
                        "buy_response": short(buy_resp, 250),
                    }
                )
                g.cleanup()
                continue
            live2 = refreshed_side(g, live_entry)
            if not live2:
                over_exit = {
                    "skip": "exit quote vanished after entry fill",
                    "ticker": ticker,
                    "side": side,
                    "entry_fill": bought,
                }
                status = "FAIL"
                break
            try:
                over_resp = g.client.place_exit(ticker, side, 3, live2["exit_bid"])
            except Exception as exc:
                over_resp = {"error": api_error(exc)}
            time.sleep(1.0)
            g.cleanup()
            clean, current = g.positions_match_baseline()
            over_order = order_from(over_resp) if isinstance(over_resp, dict) else None
            over_fill = fill_count(over_order or over_resp)
            over_ok = clean and over_fill <= bought + 1e-9
            status = "PASS" if no_hold_ok and over_ok else "FAIL"
            over_exit = {
                "ticker": ticker,
                "side": side,
                "response": short(over_resp),
                "over_fill": over_fill,
                "entry_fill": bought,
                "positions_after": current,
                "clean": clean,
            }
        if over_exit is None:
            over_exit = {"skip": "could not establish 1-contract holding from current live candidates"}
            status = "SKIP" if no_hold_ok else "FAIL"
        evidence = (
            f"no_hold={no_hold_ticker} {no_hold_side} "
            f"{'4xx' if isinstance(no_hold, dict) and no_hold.get('error') else 'fill=' + str(no_hold_fill)}; "
            f"over_exit={short(over_exit, 220)}"
        )
        return result(
            status,
            evidence,
            no_hold_ticker=no_hold_ticker,
            no_hold_side=no_hold_side,
            no_hold=short(no_hold),
            over_exit=over_exit,
            entry_attempts=entry_attempts,
        )
    except Exception as exc:
        return result("FAIL", f"exception during reduce_only boundary: {api_error(exc)['message']}", error=api_error(exc))
    finally:
        g.cleanup()


def test_t6(g: Gym) -> dict:
    m = g.discovery["rest"]
    if not m:
        return result("SKIP", "no active market available for rate-limit place/cancel probe")
    ticker = m["ticker"]
    side, price = choose_rest_params(m)
    start = time.monotonic()
    attempts = 0
    first_429 = None
    errors = []
    try:
        while time.monotonic() - start < 60:
            attempts += 1
            coid = g.coid(f"T6-{attempts}")
            order = None
            try:
                resp, order = g.place(
                    ticker, side, 1, price, "good_till_canceled", f"T6-{attempts}",
                    client_order_id=coid,
                )
            except Exception as exc:
                err = api_error(exc)
                if err["is_429"]:
                    first_429 = {"seq": attempts, "phase": "place", "elapsed_s": round(time.monotonic() - start, 3), "error": err}
                    break
                errors.append({"seq": attempts, "phase": "place", "error": err})
                break
            try:
                g.client.cancel_order(str(order.get("order_id")))
            except Exception as exc:
                err = api_error(exc)
                if err["is_429"]:
                    first_429 = {"seq": attempts, "phase": "cancel", "elapsed_s": round(time.monotonic() - start, 3), "error": err}
                    break
                errors.append({"seq": attempts, "phase": "cancel", "error": err})
                break
            sleep_s = max(0.05, 0.30 - attempts * 0.005)
            time.sleep(sleep_s)

        recovery_s = None
        if first_429:
            recovery_start = time.monotonic()
            for _ in range(15):
                try:
                    g.client.balance()
                    recovery_s = round(time.monotonic() - recovery_start, 3)
                    break
                except Exception as exc:
                    if not api_error(exc)["is_429"]:
                        recovery_s = round(time.monotonic() - recovery_start, 3)
                        break
                    time.sleep(2.0)
            first_429["recovery_s"] = recovery_s
        g.cleanup()
        status = "PASS" if not errors else "FAIL"
        evidence = (
            f"{attempts} place/cancel attempts in {round(time.monotonic() - start, 1)}s; "
            f"first_429={first_429}"
        )
        return result(
            status,
            evidence,
            ticker=ticker,
            side=side,
            price=price,
            attempts=attempts,
            first_429=first_429,
            errors=errors,
        )
    except Exception as exc:
        return result("FAIL", f"exception during rate-limit probe: {api_error(exc)['message']}", error=api_error(exc))
    finally:
        g.cleanup()


def test_t7(g: Gym) -> dict:
    m = g.discovery["rest"]
    if not m:
        return result("SKIP", "no active market available for client_order_id idempotency")
    ticker = m["ticker"]
    side, price = choose_rest_params(m)
    coid = g.coid("T7-dup")
    first_order = None
    try:
        first_resp, first_order = g.place(
            ticker, side, 1, price, "good_till_canceled", "T7a", client_order_id=coid
        )
        first_oid = first_order.get("order_id")
        second = None
        try:
            second_resp, second_order = g.place(
                ticker, side, 1, price, "good_till_canceled", "T7b", client_order_id=coid
            )
            second = {"response": second_resp, "order": second_order}
            second_oid = second_order.get("order_id")
            ok = second_oid == first_oid
            semantic = "same_order_echo" if ok else "different_order_accepted"
        except Exception as exc:
            err = api_error(exc)
            second = {"error": err}
            ok = err["is_4xx"]
            semantic = "4xx_reject" if ok else "non_4xx_error"
        status = "PASS" if ok else "FAIL"
        evidence = f"{ticker} duplicate coid={coid}; semantic={semantic}; second={short(second, 220)}"
        return result(
            status,
            evidence,
            ticker=ticker,
            side=side,
            price=price,
            client_order_id=coid,
            first_order_id=first_oid,
            first_response=short(first_resp),
            second=short(second),
            semantic=semantic,
        )
    except Exception as exc:
        return result("FAIL", f"exception during idempotency probe: {api_error(exc)['message']}", error=api_error(exc))
    finally:
        g.cancel_if_active(first_order)
        g.cleanup()


def test_t8(_: Gym) -> dict:
    return result(
        "SKIP",
        "optional private WS probe skipped: 20-minute single-run budget and no repo implementation for private WS auth",
    )


TESTS = [
    ("T1", test_t1),
    ("T2", test_t2),
    ("T3", test_t3),
    ("T4", test_t4),
    ("T5", test_t5),
    ("T6", test_t6),
    ("T7", test_t7),
    ("T8", test_t8),
]


def main() -> int:
    started = time.monotonic()
    client = KalshiLive(timeout=20, demo=True)
    if client.demo is not True or "demo" not in str(client.base).lower():
        sys.exit(2)

    g = Gym(client)
    results: dict[str, dict] = {}
    meta = {
        "ts": utc_now(),
        "env": "demo",
        "run_id": RUN_ID,
        "base": client.base,
        "baseline_positions": g.baseline_positions,
        "discovery": {
            "market_count": g.discovery["market_count"],
            "rest_ticker": (g.discovery["rest"] or {}).get("ticker"),
            "live_ticker": ((g.discovery["live"] or {}).get("market") or {}).get("ticker"),
            "live_side": (g.discovery["live"] or {}).get("side"),
            "capped_ticker": ((g.discovery["capped"] or {}).get("market") or {}).get("ticker"),
            "capped_side": (g.discovery["capped"] or {}).get("side"),
            "active_order_tickers_skipped": g.discovery["active_order_tickers"],
        },
    }

    try:
        for label, fn in TESTS:
            try:
                row = fn(g)
            except Exception as exc:
                row = result(
                    "FAIL",
                    f"unhandled exception: {api_error(exc)['message']}",
                    error=api_error(exc),
                    traceback=traceback.format_exc(limit=6),
                )
                g.cleanup()
            results[label] = row
            emit(label, row)
    finally:
        g.cleanup()

    clean, final_positions = g.positions_match_baseline()
    elapsed_s = round(time.monotonic() - started, 3)
    if clean:
        print(f"CLEANUP PASS | positions match baseline; elapsed_s={elapsed_s}", flush=True)
    else:
        print(
            f"CLEANUP FAIL | baseline={g.baseline_positions}; final={final_positions}; "
            f"errors={short(g.cleanup_errors, 500)}",
            flush=True,
        )

    payload = {
        **meta,
        "completed_ts": utc_now(),
        "elapsed_s": elapsed_s,
        "results": results,
        "clean_exit": clean,
        "final_positions": final_positions,
        "cleanup_errors": g.cleanup_errors,
    }
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    tmp_path = RESULTS_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, RESULTS_PATH)
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
