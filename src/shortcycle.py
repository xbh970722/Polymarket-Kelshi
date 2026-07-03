"""Short-cycle quant lane: hourly crypto terminal-value markets (KXBTCD/KXETHD).

Settlement = average of the final 60s of CF BRTI before the top of the hour;
YES = settle above strike. Fair value is a lognormal terminal probability using
minute-level realized vol — no LLM involved. The engine's fee/Kelly/risk gates
still decide; this module only supplies q_model and the candidate list.

Runs mechanically every hour (scheduled task). Trades are real (practice sizing),
settle fast, and feed the Brier calibration ledger 24x faster than monthly markets.
"""
import datetime as dt
import math
import statistics

import requests

from .kalshi_client import KalshiPublic, normalize_market

SPOT_PRODUCT = {"KXBTCD": "BTC-USD", "KXETHD": "ETH-USD"}
# 15-minute up/down series: settle = (60s index avg before window end) >= (avg before window start)
SPOT_15M = {"KXBTC15M": "BTC-USD", "KXETH15M": "ETH-USD", "KXSOL15M": "SOL-USD"}


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def minute_vol(product: str, lookback_min: int = 180) -> tuple[float, float]:
    """Return (spot, per-minute log-return std) from Coinbase 1-min candles."""
    s = requests.Session()
    s.headers["User-Agent"] = "shortcycle/0.1"
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(minutes=min(lookback_min, 300))
    r = s.get(f"https://api.exchange.coinbase.com/products/{product}/candles",
              params={"granularity": 60, "start": start.isoformat(), "end": end.isoformat()},
              timeout=20)
    r.raise_for_status()
    closes = [c[4] for c in sorted(r.json())]
    if len(closes) < 30:
        raise RuntimeError(f"not enough 1-min candles for {product}: {len(closes)}")
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0]
    spot = float(s.get(f"https://api.exchange.coinbase.com/products/{product}/ticker",
                       timeout=15).json()["price"])
    return spot, statistics.stdev(rets)


def strike_of(ticker: str) -> float | None:
    """KXBTCD-26JUL0312-T62199.99 -> 62199.99 (T = 'at or above' threshold)."""
    tail = ticker.rsplit("-", 1)[-1]
    if not tail.startswith("T"):
        return None
    try:
        return float(tail[1:])
    except ValueError:
        return None


def _ewma_minute_vol(product: str) -> tuple[float, float]:
    """Spot + EWMA per-minute vol (lambda=.94 over ~60m) floored by 0.6x the 180m std,
    guarding against calm-then-burst underestimation."""
    s = requests.Session()
    s.headers["User-Agent"] = "shortcycle/0.1"
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(minutes=185)
    r = s.get(f"https://api.exchange.coinbase.com/products/{product}/candles",
              params={"granularity": 60, "start": start.isoformat(), "end": end.isoformat()},
              timeout=20)
    r.raise_for_status()
    closes = [c[4] for c in sorted(r.json())]
    if len(closes) < 40:
        raise RuntimeError(f"not enough candles for {product}")
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0]
    long_std = statistics.stdev(rets)
    lam, var = 0.94, rets[-60] ** 2 if len(rets) >= 60 else rets[0] ** 2
    for x in rets[-60:]:
        var = lam * var + (1 - lam) * x * x
    sigma = max(math.sqrt(var), 0.6 * long_std)
    spot = float(s.get(f"https://api.exchange.coinbase.com/products/{product}/ticker",
                       timeout=15).json()["price"])
    return spot, sigma


def _prev_settlement(api: KalshiPublic, series: str, window_start: dt.datetime) -> float | None:
    """EXACT reference: the previous 15m window's published settlement value
    (its 60s index average IS this window's starting reference)."""
    try:
        page = api._get("/markets", series_ticker=series, status="settled", limit=4)
    except Exception:
        return None
    target = window_start.strftime("%Y-%m-%dT%H:%M")
    for m in page.get("markets", []):
        ct = (m.get("close_time") or "")[:16]
        ev = m.get("expiration_value")
        if ct == target and ev:
            try:
                return float(ev)
            except ValueError:
                return None
    return None


def candidates_15m(cfg: dict) -> list[dict]:
    """15-minute up/down markets — certainty-zone design (SHORTCYCLE_DESIGN.md):

    * reference price = previous window's exact published settlement (no proxy error)
    * only hunt tau in [2,6] min where direction is nearly locked
    * only act when q is OUTSIDE the coin-flip band (certainty gate) AND the
      spot-vs-reference distance exceeds 2 sigma (basis guard) — a few bps of
      Coinbase-vs-BRTI basis then cannot flip the signal
    """
    sc = cfg["shortcycle"]
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc)
    lo_q, hi_q = sc.get("certainty_band", [0.22, 0.78])
    out = []
    for series in sc.get("series_15m", []):
        product = SPOT_15M.get(series)
        if not product:
            continue
        try:
            page = api._get("/markets", series_ticker=series, status="open", limit=20)
        except Exception as e:
            print(f"WARN {series}: {e}")
            continue
        for mr in page.get("markets", []):
            m = normalize_market(mr)
            if m["status"] != "active" or not m["close_time"]:
                continue
            close = dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
            tau_min = (close - now).total_seconds() / 60.0
            if not (sc.get("min_minutes_15m", 2) <= tau_min <= sc.get("max_minutes_15m", 6)):
                continue
            if not (m["yes_bid"] > 0 and 0.03 <= m["yes_ask"] <= 0.97):
                continue
            ref = _prev_settlement(api, series, close - dt.timedelta(minutes=15))
            if ref is None:
                print(f"PASS  {m['ticker']}: previous settlement value unavailable")
                continue
            try:
                spot, sigma_min = _ewma_minute_vol(product)
            except Exception as e:
                print(f"WARN {series}: vol fetch failed ({e})")
                break
            dist = math.log(spot / ref)
            if abs(dist) < 2.0 * sigma_min:            # basis guard: signal inside noise
                continue
            tau_eff = max(tau_min - 0.75, 0.5)         # 60s-average endpoints shave variance
            q = _phi(dist / (sigma_min * math.sqrt(tau_eff)))
            if lo_q < q < hi_q:                        # certainty gate: skip coin-flip zone
                continue
            out.append({"ticker": m["ticker"], "series": series, "strike": ref,
                        "spot": spot, "sigma_min": sigma_min, "tau_min": round(tau_min, 1),
                        "yes_bid": m["yes_bid"], "yes_ask": m["yes_ask"],
                        "no_ask": m["no_ask"], "q_model": round(min(max(q, 0.001), 0.999), 4),
                        "mid": round((m["yes_bid"] + m["yes_ask"]) / 2, 4)})
    return out


def candidates(cfg: dict) -> list[dict]:
    """Active threshold strikes in the trade window with a model fair value."""
    sc = cfg["shortcycle"]
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for series in sc["series"]:
        product = SPOT_PRODUCT.get(series)
        if not product:
            continue
        try:
            spot, sigma_min = minute_vol(product, sc.get("vol_lookback_min", 180))
        except Exception as e:
            print(f"WARN {series}: vol fetch failed ({e})")
            continue
        page = api._get("/markets", series_ticker=series, status="open", limit=100)
        for mr in page.get("markets", []):
            m = normalize_market(mr)
            k = strike_of(m["ticker"])
            if k is None or m["status"] != "active" or not m["close_time"]:
                continue
            close = dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
            tau_min = (close - now).total_seconds() / 60.0
            if not (sc["min_minutes_to_close"] <= tau_min <= sc["max_minutes_to_close"]):
                continue
            if not (m["yes_bid"] > 0 and 0.03 <= m["yes_ask"] <= 0.97):
                continue
            # terminal lognormal: settle is a 60s average -> tiny variance reduction, ignored
            denom = sigma_min * math.sqrt(max(tau_min, 1.0))
            q_model = _phi(math.log(spot / k) / denom) if denom > 0 else (1.0 if spot > k else 0.0)
            out.append({"ticker": m["ticker"], "series": series, "strike": k,
                        "spot": spot, "sigma_min": sigma_min, "tau_min": round(tau_min, 1),
                        "yes_bid": m["yes_bid"], "yes_ask": m["yes_ask"],
                        "no_ask": m["no_ask"], "q_model": round(q_model, 4),
                        "mid": round((m["yes_bid"] + m["yes_ask"]) / 2, 4)})
    return out
