"""Synthetic test of the live order state machine on a throwaway DB."""
import sys
from pathlib import Path
sys.path.insert(0, r"D:\Polymarket-Kelshi")
import src.ledger as ledger

ledger.DB = Path(r"C:\Users\xuboh\AppData\Local\Temp\claude\D--Polymarket-Kelshi\acd916af-5be2-415e-97cc-68147374adb7\scratchpad\test_ledger.db")
if ledger.DB.exists():
    ledger.DB.unlink()

# paper insert (default open)
t1 = ledger.insert_trade(mode="paper", ticker="TEST-A", title="t", side="yes",
                         price=0.50, contracts=10, cost_usd=5.10, fee_usd=0.10,
                         q_claude=0.6, q_codex=0.62, q_consensus=0.61,
                         market_prob=0.50, edge_net=0.09, rationale="test")
# live pending inserts
t2 = ledger.insert_trade(mode="live", ticker="TEST-B", title="t", side="no",
                         price=0.10, contracts=20, cost_usd=2.20, fee_usd=0.20,
                         q_claude=0.8, q_codex=0.82, q_consensus=0.81,
                         market_prob=0.90, edge_net=0.08, rationale="test",
                         status="pending")
t3 = ledger.insert_trade(mode="live", ticker="TEST-C", title="t", side="yes",
                         price=0.30, contracts=5, cost_usd=1.60, fee_usd=0.10,
                         q_claude=0.4, q_codex=0.42, q_consensus=0.41,
                         market_prob=0.30, edge_net=0.06, rationale="test",
                         status="pending")

s = ledger.stats()
assert s["open_positions"] == 3, s          # open + 2 pending counted in exposure
assert abs(s["open_exposure"] - 8.90) < 0.01, s
assert len(ledger.pending_trades()) == 2

ledger.mark_placed(t2, "ord_123")
assert len(ledger.pending_trades()) == 1
assert any(t["order_id"] == "ord_123" and t["status"] == "open" for t in ledger.open_trades())

ledger.void_trade(t3, "user cancelled")
assert len(ledger.pending_trades()) == 0
assert ledger.stats()["open_positions"] == 2   # voided excluded

ledger.settle_trade(t1, "yes", 4.90)
cal = ledger.calibration()
assert cal["n_settled"] == 1 and cal["realized_pnl"] == 4.90

print("ALL LEDGER LIVE-STATE TESTS PASSED")
