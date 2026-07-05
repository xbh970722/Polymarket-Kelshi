"""Synthetic test of swing exit: plan -> take-profit -> close -> P&L -> Brier exclusion."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, r"D:\Polymarket-Kelshi")
import src.ledger as ledger
from src import engine
from src.kalshi_client import taker_fee_usd

ledger.DB = Path(r"C:\Users\xuboh\AppData\Local\Temp\claude\D--Polymarket-Kelshi\acd916af-5be2-415e-97cc-68147374adb7\scratchpad\test_swing.db")
if ledger.DB.exists():
    ledger.DB.unlink()

cfg = {"swing": {"enabled": True, "take_profit_capture": 0.6, "min_target_move": 0.03,
                 "stop_loss_frac": 0.5, "review_after_days": 5}}

# --- plan_exit logic ---
# YES entered at 0.11, consensus 0.17 -> gap 0.06, target = 0.11 + 0.6*0.06 = 0.146 (>3c move) -> swing
p = engine.plan_exit(0.17, 0.11, cfg)
assert p.exit_type == "swing" and abs(p.target_price - 0.146) < 1e-6, p
assert abs(p.stop_price - 0.055) < 1e-6, p
# thin edge: entered 0.11, consensus 0.12 -> target move <3c -> hold
p2 = engine.plan_exit(0.12, 0.11, cfg)
assert p2.exit_type == "hold", p2

# --- check_exit ---
assert engine.check_exit(0.146, 0.055, 0.15)[0] == "take_profit"   # bid above target
assert engine.check_exit(0.146, 0.055, 0.05)[0] == "stop_loss"     # bid below stop
assert engine.check_exit(0.146, 0.055, 0.11)[0] is None            # in between -> hold

# --- full ledger flow: open swing, take profit, verify accounting ---
tid = ledger.insert_trade(mode="paper", ticker="TEST-SWING", title="t", side="yes",
                          price=0.11, contracts=81, cost_usd=9.47, fee_usd=0.56,
                          q_claude=0.16, q_codex=0.18, q_consensus=0.17,
                          market_prob=0.10, edge_net=0.05, rationale="swing test",
                          status="open")
ledger.set_exit_plan(tid, "swing", 0.146, 0.055, "2026-07-08T00:00:00")

# price converges to 0.15 (>= target 0.146) -> take profit
exit_px = 0.15
fee = taker_fee_usd(exit_px, 81)
pnl = round(81 * exit_px - fee - 9.47, 2)     # 12.15 - fee - 9.47
ledger.close_position(tid, exit_px, pnl, "take_profit@15c")

closed = [t for t in ledger._conn().execute("SELECT * FROM trades WHERE id=?", (tid,))]
row = dict(closed[0])
assert row["status"] == "closed", row["status"]
assert row["exit_price"] == 0.15
assert row["pnl_usd"] == pnl and pnl > 0, pnl
assert "take_profit" in row["rationale"]

# Brier calibration must EXCLUDE swing-closed (no resolved outcome); swing_summary INCLUDES it
cal = ledger.calibration()
assert cal.get("n_settled", 0) == 0, "closed swing must not count as settled"
sw = ledger.swing_summary()
assert sw["n_closed"] == 1 and abs(sw["swing_pnl"] - pnl) < 1e-6, sw

print(f"ALL SWING TESTS PASSED  (take-profit pnl=${pnl:+.2f}, Brier n_settled={cal.get('n_settled',0)}, "
      f"swing_pnl=${sw['swing_pnl']:+.2f})")
