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
API = "/trade-api/v2"


class LiveAuthError(RuntimeError):
    pass


def _load_credentials():
    key_id = os.environ.get("KALSHI_API_KEY_ID")
    key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    if not key_id or not key_path:
        raise LiveAuthError(
            "KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH not set. "
            "Create an API key at kalshi.com -> Account -> API Keys, save the .pem, "
            "then set both environment variables (see README '真钱交易配置').")
    if not os.path.exists(key_path):
        raise LiveAuthError(f"private key file not found: {key_path}")
    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    return key_id, private_key


class KalshiLive:
    def __init__(self, timeout: int = 20):
        self.key_id, self.pk = _load_credentials()
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

    def _req(self, method: str, path: str, body: dict | None = None):
        r = self.s.request(method, BASE + path, json=body,
                           headers=self._headers(method, path), timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:400]}")
        return r.json() if r.text else {}

    # ---- read-only ----
    def balance(self) -> dict:
        return self._req("GET", f"{API}/portfolio/balance")

    def positions(self) -> dict:
        return self._req("GET", f"{API}/portfolio/positions")

    # ---- money-moving ----
    def place_limit(self, ticker: str, side: str, count: int, price_prob: float) -> dict:
        """Buy `count` contracts of yes/no at a limit price (probability 0-1)."""
        assert side in ("yes", "no")
        cents = int(round(price_prob * 100))
        assert 1 <= cents <= 99, f"limit price out of range: {cents}c"
        body = {"ticker": ticker, "action": "buy", "side": side, "count": int(count),
                "type": "limit", "client_order_id": str(uuid.uuid4())}
        body["yes_price" if side == "yes" else "no_price"] = cents
        return self._req("POST", f"{API}/portfolio/orders", body)
