"""Kalshi public-data client. Market data endpoints need no authentication.

The 2026 API denominates prices in dollar-string fields (yes_ask_dollars, ...)
at deci-cent resolution, and contract counts as fixed-point strings (volume_24h_fp).
normalize_market() converts one raw market dict to plain floats: prices become
probabilities in [0, 1], sizes become float contract counts.
"""
import math
import time

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def normalize_market(m: dict) -> dict:
    return {
        "ticker": m.get("ticker"),
        "status": m.get("status"),
        "yes_bid": _f(m.get("yes_bid_dollars")),
        "yes_ask": _f(m.get("yes_ask_dollars")),
        "no_bid": _f(m.get("no_bid_dollars")),
        "no_ask": _f(m.get("no_ask_dollars")),
        "last_price": _f(m.get("last_price_dollars")),
        "volume_24h": _f(m.get("volume_24h_fp")),
        "volume": _f(m.get("volume_fp")),
        "open_interest": _f(m.get("open_interest_fp")),
        "liquidity_usd": _f(m.get("liquidity_dollars")),
        "close_time": m.get("close_time"),
        "result": m.get("result"),
        "is_provisional": bool(m.get("is_provisional")),
        "title": m.get("title"),
        "yes_sub_title": m.get("yes_sub_title"),
        "rules_primary": m.get("rules_primary"),
    }


class KalshiPublic:
    def __init__(self, timeout: int = 15):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "paper-research-pipeline/0.1"
        self.timeout = timeout

    def _get(self, path: str, **params):
        for attempt in range(3):
            r = self.s.get(f"{BASE}{path}", params=params, timeout=self.timeout)
            if r.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"rate-limited on {path}")

    def events(self, status="open", cursor=None, limit=200, with_nested_markets=True):
        params = {"status": status, "limit": limit,
                  "with_nested_markets": str(with_nested_markets).lower()}
        if cursor:
            params["cursor"] = cursor
        return self._get("/events", **params)

    def iter_events(self, status="open", max_pages=25):
        cursor = None
        for _ in range(max_pages):
            page = self.events(status=status, cursor=cursor)
            yield from page.get("events", [])
            cursor = page.get("cursor")
            if not cursor:
                break

    def open_markets(self, series_ticker: str, status: str = "open",
                     max_pages: int = 5) -> list[dict]:
        """All markets of a series across pages. R3-CODEX-3 MED fix: a single
        limit=100 page can truncate busy series (e.g. daily crypto with strikes
        across many hourly events) and silently hide tradable windows."""
        out: list[dict] = []
        cursor = None
        for _ in range(max_pages):
            params = {"series_ticker": series_ticker, "status": status, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            page = self._get("/markets", **params)
            out += page.get("markets", [])
            cursor = page.get("cursor")
            if not cursor:
                break
        return out

    def market(self, ticker: str) -> dict:
        return self._get(f"/markets/{ticker}")["market"]

    def market_norm(self, ticker: str) -> dict:
        return normalize_market(self.market(ticker))

    # (orderbook() deleted 2026-07-04 R4-FABLE-B: parsed a pre-2026 response shape
    #  (KeyError live), zero callers — re-add against the current API when H9 needs
    #  book depth.)


def taker_fee_usd(price: float, contracts: float) -> float:
    """Kalshi general schedule: 0.07 * C * P * (1-P), rounded UP to the cent.

    price is the per-contract price as a probability in (0, 1).
    The 1e-9 guard stops float artifacts from bumping the ceil a cent too high.
    """
    raw = 0.07 * contracts * price * (1.0 - price)
    return math.ceil(raw * 100 - 1e-9) / 100.0
