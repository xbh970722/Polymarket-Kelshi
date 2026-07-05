"""Round-3 regression battery: pins the money-path semantics the R3 panel flagged
as UNTESTED (Fable coverage gap #1/#2). Pure offline — fake client/api, temp DB."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"D:\Polymarket-Kelshi")
import src.ledger as ledger
from src.kalshi_client import taker_fee_usd
from src.pipeline import OrderAmbiguous, _decisive_ioc

ledger.DB = Path(tempfile.gettempdir()) / "test_r3_fixes.db"
if ledger.DB.exists():
    ledger.DB.unlink()


def _row(**kw):
    base = dict(mode="live", ticker="TEST-X", title="shortcycle TEST", side="yes",
                price=0.50, contracts=2, cost_usd=1.02, fee_usd=0.02,
                q_claude=0.6, q_codex=0.6, q_consensus=0.6, market_prob=0.5,
                edge_net=0.05, rationale="r3", status="open")
    base.update(kw)
    return ledger.insert_trade(**base)


# ---- 1. stale-pending split: no order_id -> voided; with order_id -> unknown ----
old = "2020-01-01T00:00:00"
a = _row(ticker="TTL-A", status="pending", ts=old)                    # never submitted
b = _row(ticker="TTL-B", status="pending", ts=old, order_id="co-1")   # owned an order id
n_unknown = ledger.void_stale_pending(60)
with ledger._conn() as c:
    sa = c.execute("SELECT status FROM trades WHERE id=?", (a,)).fetchone()[0]
    sb = c.execute("SELECT status FROM trades WHERE id=?", (b,)).fetchone()[0]
assert sa == "voided", f"never-submitted stale pending must void, got {sa}"
assert sb == "unknown", f"submitted stale pending must freeze unknown, got {sb}"
assert n_unknown == 1, n_unknown
print("PASS 1: stale-pending TTL splits voided/unknown by order identity")

# ---- 2. unknown blocks re-entry (dedup layers) ----
assert ledger.has_open_position("TTL-B", "live"), "unknown must block same ticker"
assert not ledger.has_open_position("TTL-A", "live"), "voided must NOT block"
acts = {t["ticker"] for t in ledger.active_trades("live")}
assert "TTL-B" in acts and "TTL-A" not in acts, acts
print("PASS 2: unknown blocks dedup; voided releases")

# ---- 3. record_fill promotes unknown/pending to open atomically ----
ledger.record_fill(b, 3, 0.94, 2.84, 0.02, "ord-9")
with ledger._conn() as c:
    r = dict(c.execute("SELECT * FROM trades WHERE id=?", (b,)).fetchone())
assert (r["status"], r["contracts"], r["price"], r["order_id"]) == ("open", 3, 0.94, "ord-9"), r
print("PASS 3: record_fill single-transaction promotion")

# ---- 4. split_close conserves contracts/cost and carries audit columns ----
p = _row(ticker="SPL-1", contracts=3, cost_usd=1.53, fee_usd=0.03, order_id="ord-p",
         exit_type="tp", target_price=0.8, stop_price=0.3,
         review_after_ts="2027-01-01T00:00:00")
ledger.split_close(p, 1, 0.70, 0.01, "tp@70c")
with ledger._conn() as c:
    parent = dict(c.execute("SELECT * FROM trades WHERE id=?", (p,)).fetchone())
    child = dict(c.execute("SELECT * FROM trades WHERE ticker='SPL-1' AND id != ?",
                           (p,)).fetchone())
assert parent["contracts"] == 2 and child["contracts"] == 1
assert abs(parent["cost_usd"] + child["cost_usd"] - 1.53) < 0.011, (parent, child)
assert child["order_id"] == "ord-p" and child["exit_type"] == "tp"
assert child["status"] == "closed" and child["review_after_ts"] == "2027-01-01T00:00:00"
print("PASS 4: split_close conservation + audit carry")


# ---- 5. _decisive_ioc: frame, caps, ambiguity taxonomy (fake exchange) ----
class FakeApi:
    def __init__(self, yes_ask):
        self.yes_ask = yes_ask

    def market_norm(self, tk):
        return {"yes_bid": self.yes_ask - 0.02, "yes_ask": self.yes_ask,
                "no_bid": round(1 - self.yes_ask - 0.01, 4),
                "no_ask": round(1 - self.yes_ask + 0.02, 4)}


class FakeClient:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.sent = resp, exc, None

    def place_limit(self, ticker, side, contracts, px, tif="immediate_or_cancel",
                    client_order_id=None):
        if self.exc:
            raise self.exc
        self.sent = {"contracts": contracts, "px": px, "coid": client_order_id}
        return self.resp

    def cancel_order(self, oid):
        pass


# 5a. NO-side: exchange average (YES-leg 0.06) must book as held-side 0.94
cl = FakeClient(resp={"order_id": "o1", "fill_count": "2.00",
                      "average_fill_price": "0.06"})
n, px, fee, oid = _decisive_ioc(cl, FakeApi(0.07), "T", "no", 2, 0.01, -1.0,
                                slippage=0.0, price_cap=0.99)
assert n == 2 and abs(px - 0.94) < 1e-9, (n, px)
# 5b. fallback (no average reported) stays in held-side frame — NO double conversion
cl = FakeClient(resp={"order_id": "o2", "fill_count_fp": "1.00"})
n, px, fee, oid = _decisive_ioc(cl, FakeApi(0.07), "T", "no", 1, 0.01, -1.0,
                                slippage=0.0, price_cap=0.99)
assert n == 1 and abs(px - 0.95) < 1e-9, (n, px)   # no_ask 0.95 crossed at slip 0
print("PASS 5ab: NO-frame conversion (exchange avg converted; fallback untouched)")

# 5c. fresh-price cap recheck shrinks contracts to fit max_cost_usd
cl = FakeClient(resp={"order_id": "o3", "fill_count": "2.00"})
n, px, fee, oid = _decisive_ioc(cl, FakeApi(0.25), "T", "yes", 5, 0.99, 0.0,
                                slippage=0.01, max_cost_usd=0.60)
assert cl.sent["contracts"] == 2, cl.sent   # 5 would cost ~$1.34 -> shrink to 2
# 5d. cap below even one contract -> refuse, nothing sent
cl = FakeClient(resp={"order_id": "o4", "fill_count": "1.00"})
n, px, *_ = _decisive_ioc(cl, FakeApi(0.25), "T", "yes", 3, 0.99, 0.0,
                          slippage=0.01, max_cost_usd=0.10)
assert n == 0 and cl.sent is None, (n, cl.sent)
print("PASS 5cd: fresh-price dollar-cap recheck (shrink / refuse)")

# 5e. HTTP 4xx = clean reject (no exception, nothing booked)
cl = FakeClient(exc=RuntimeError("POST /x -> HTTP 400: insufficient_balance"))
n, reason, *_ = _decisive_ioc(cl, FakeApi(0.50), "T", "yes", 1, 0.99, 0.0)
assert n == 0 and "rejected" in reason, (n, reason)
# 5f. HTTP 5xx = ambiguous
try:
    _decisive_ioc(FakeClient(exc=RuntimeError("POST /x -> HTTP 502: bad gateway")),
                  FakeApi(0.50), "T", "yes", 1, 0.99, 0.0)
    raise AssertionError("5xx must raise OrderAmbiguous")
except OrderAmbiguous:
    pass
# 5g. timeout/connection = ambiguous
try:
    _decisive_ioc(FakeClient(exc=TimeoutError("timed out")),
                  FakeApi(0.50), "T", "yes", 1, 0.99, 0.0)
    raise AssertionError("timeout must raise OrderAmbiguous")
except OrderAmbiguous:
    pass
# 5h. fractional fill = ambiguous, never truncated to no-fill
try:
    _decisive_ioc(FakeClient(resp={"order_id": "o5", "fill_count_fp": "0.50"}),
                  FakeApi(0.50), "T", "yes", 1, 0.99, 0.0)
    raise AssertionError("fractional fill must raise OrderAmbiguous")
except OrderAmbiguous:
    pass
print("PASS 5efgh: ambiguity taxonomy (4xx reject / 5xx / timeout / fractional)")

# ---- 6. checkpoint runs (WAL fold) ----
ledger.checkpoint()
print("PASS 6: wal checkpoint")

# ---- 7. _http_status: parse live._req's prefix, ignore lookalikes in the body ----
from src.pipeline import _http_status
assert _http_status(RuntimeError("POST /x -> HTTP 400: insufficient")) == 400
assert _http_status(RuntimeError("POST /x -> HTTP 502: <html>HTTP 400</html>")) == 502
assert _http_status(TimeoutError("timed out")) is None
try:
    _decisive_ioc(FakeClient(exc=RuntimeError("POST /x -> HTTP 502: body HTTP 400 page")),
                  FakeApi(0.50), "T", "yes", 1, 0.99, 0.0)
    raise AssertionError("5xx with 4xx-lookalike body must be OrderAmbiguous")
except OrderAmbiguous:
    pass
print("PASS 7: http status prefix parse (body lookalikes stay ambiguous)")

print("ALL R3 REGRESSION TESTS PASSED")
