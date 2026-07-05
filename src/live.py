"""Kalshi authenticated trading client. LIVE MONEY — every call here can move real funds.

Auth: RSA-PSS(SHA256) signature over (timestamp_ms + METHOD + path), headers
KALSHI-ACCESS-KEY / KALSHI-ACCESS-TIMESTAMP / KALSHI-ACCESS-SIGNATURE.
Credentials come from environment variables only (never stored in the repo):
    KALSHI_API_KEY_ID        - API key id from kalshi.com -> Account -> API Keys
    KALSHI_PRIVATE_KEY_PATH  - path to the RSA private key .pem downloaded at creation
"""
import base64
import os
import time
import uuid

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE = "https://api.elections.kalshi.com"
DEMO_BASE = "https://demo-api.kalshi.co"     # paper-money environment (C1 verified
API = "/trade-api/v2"                        # 2026-07-05); same auth scheme


class LiveAuthError(RuntimeError):
    pass


_SECRETS_DIR = r"D:\kalshi-secrets"          # outside the repo; never committed


def _load_credentials(demo: bool = False):
    """Load (key_id, private_key). demo=True selects the DEMO environment's
    credentials — separate account, separate key, fake money. VALUES 5f: all
    test batteries / probes must run demo; prod keys are for the money paths."""
    env_id = "KALSHI_DEMO_API_KEY_ID" if demo else "KALSHI_API_KEY_ID"
    env_path = "KALSHI_DEMO_PRIVATE_KEY_PATH" if demo else "KALSHI_PRIVATE_KEY_PATH"
    id_name = "demo_key_id.txt" if demo else "key_id.txt"
    pem_name = "kalshi_demo.pem" if demo else "kalshi_test.pem"
    key_id = os.environ.get(env_id)
    key_path = os.environ.get(env_path)
    # file fallback so detached processes (quant loop, schedulers) work without env vars
    if not key_id:
        id_file = os.path.join(_SECRETS_DIR, id_name)
        if os.path.exists(id_file):
            key_id = open(id_file).read().strip()
    if not key_path:
        pem_default = os.path.join(_SECRETS_DIR, pem_name)
        if os.path.exists(pem_default):
            key_path = pem_default
    if not key_id or not key_path:
        raise LiveAuthError(
            f"credentials not found: set {env_id} / {env_path} "
            f"or place {id_name} + {pem_name} in D:\\kalshi-secrets\\ "
            "(see README '真钱交易配置').")
    if not os.path.exists(key_path):
        raise LiveAuthError(f"private key file not found: {key_path}")
    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    return key_id, private_key


class KalshiLive:
    def __init__(self, timeout: int = 20, demo: bool = False):
        self.key_id, self.pk = _load_credentials(demo=demo)
        self.demo = demo
        self.base = DEMO_BASE if demo else BASE
        self.s = requests.Session()
        self.timeout = timeout

    def _headers(self, method: str, path: str) -> dict:
        ts = str(int(time.time() * 1000))
        message = (ts + method.upper() + path).encode()
        signature = self.pk.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256())
        return {"KALSHI-ACCESS-KEY": self.key_id,
                "KALSHI-ACCESS-TIMESTAMP": ts,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode()}

    def _req(self, method: str, path: str, body: dict | None = None,
             params: dict | None = None):
        # signature covers the BARE path only — query params must go via `params`
        # (passing them inside `path` breaks the signature -> 401, found 2026-07-04)
        bare = path.split("?")[0]
        r = self.s.request(method, self.base + bare, json=body, params=params,
                           headers=self._headers(method, bare), timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {bare} -> HTTP {r.status_code}: {r.text[:400]}")
        return r.json() if r.text else {}

    def fills(self, ticker: str | None = None, limit: int = 50) -> dict:
        p = {"limit": limit}
        if ticker:
            p["ticker"] = ticker
        return self._req("GET", f"{API}/portfolio/fills", params=p)

    def orders(self, ticker: str | None = None, limit: int = 100) -> list[dict]:
        """Recent orders (R4-FABLE-A CRITICAL fix): the ONLY authoritative way to
        map our client_order_id to the exchange order_id — fills don't carry the
        client id, so ambiguous submits must resolve through here."""
        out: list[dict] = []
        cursor = None
        for _ in range(3):
            p: dict = {"limit": limit}
            if ticker:
                p["ticker"] = ticker
            if cursor:
                p["cursor"] = cursor
            page = self._req("GET", f"{API}/portfolio/orders", params=p)
            out += page.get("orders") or []
            cursor = page.get("cursor")
            if not cursor:
                break
        return out

    # ---- read-only ----
    def balance(self) -> dict:
        return self._req("GET", f"{API}/portfolio/balance")

    def cancel_order(self, order_id: str) -> dict:
        """Cancel a resting order (V2 path — the bare /portfolio/orders DELETE is
        deprecated with HTTP 410, found in verification 2026-07-04)."""
        return self._req("DELETE", f"{API}/portfolio/events/orders/{order_id}")

    def positions(self) -> dict:
        """All non-zero market positions. R3-CODEX-3 HIGH fix: paginate to the end —
        a single default page could hide orphan positions from reconcile once the
        account has traded enough distinct markets."""
        out: dict = {"market_positions": [], "event_positions": []}
        cursor = None
        for _ in range(20):
            params: dict = {"limit": 200, "count_filter": "position"}
            if cursor:
                params["cursor"] = cursor
            page = self._req("GET", f"{API}/portfolio/positions", params=params)
            out["market_positions"] += page.get("market_positions") or []
            out["event_positions"] += page.get("event_positions") or []
            cursor = page.get("cursor")
            if not cursor:
                break
        return out

    # ---- money-moving ----
    def place_limit(self, ticker: str, side: str, count: int, price_prob: float,
                    tif: str = "immediate_or_cancel",
                    client_order_id: str | None = None,
                    expiration_ts: int | None = None) -> dict:
        """Buy `count` contracts of yes/no at a limit price (probability 0-1).

        Kalshi V2 single-book model: `side` is the YES leg. bid = buy YES;
        ask = sell YES, which is economically buying NO at (1 - price). So a
        NO buy at no_price becomes a YES-leg 'ask' at (1 - no_price).
        Prices and counts are fixed-point dollar strings.
        tif: immediate_or_cancel (marketable) | good_till_canceled | fill_or_kill.
        """
        assert side in ("yes", "no")
        book_side = "bid" if side == "yes" else "ask"
        yes_price = price_prob if side == "yes" else 1.0 - price_prob
        yes_price = round(yes_price, 4)
        assert 0.0001 <= yes_price <= 0.9999, f"price out of range: {yes_price}"
        body = {"ticker": ticker, "side": book_side,
                "count": f"{int(count):d}.00", "price": f"{yes_price:.4f}",
                "time_in_force": tif, "self_trade_prevention_type": "taker_at_cross",
                # R3 fix: caller-supplied id lets a pre-submit ledger row own the
                # order identity, so ambiguous submits are recoverable via fills
                "client_order_id": client_order_id or str(uuid.uuid4())}
        if expiration_ts is not None:
            # R7-C3 HIGH: exchange-side auto-expiry — a resting order must die on
            # schedule even if our process does not survive to cancel it
            body["expiration_ts"] = int(expiration_ts)
        return self._req("POST", f"{API}/portfolio/events/orders", body)

    def place_exit(self, ticker: str, held_side: str, count: int, price_prob: float,
                   tif: str = "immediate_or_cancel") -> dict:
        """Close/reduce a position by selling the held side into its bid.

        held_side 'yes' -> sell YES = book side 'ask' at the YES price.
        held_side 'no'  -> flatten short-YES = book side 'bid' at (1 - no price).
        price_prob is the exit price in the HELD side's terms (its current bid).
        reduce_only guarantees this can only shrink a position, never open the opposite.
        NOTE: sell path not yet validated against a live key (buy path was, 2026-07-03).
        """
        assert held_side in ("yes", "no")
        book_side = "ask" if held_side == "yes" else "bid"
        yes_price = price_prob if held_side == "yes" else 1.0 - price_prob
        yes_price = round(yes_price, 4)
        assert 0.0001 <= yes_price <= 0.9999, f"exit price out of range: {yes_price}"
        body = {"ticker": ticker, "side": book_side,
                "count": f"{int(count):d}.00", "price": f"{yes_price:.4f}",
                "time_in_force": tif, "self_trade_prevention_type": "taker_at_cross",
                "reduce_only": True, "client_order_id": str(uuid.uuid4())}
        return self._req("POST", f"{API}/portfolio/events/orders", body)
