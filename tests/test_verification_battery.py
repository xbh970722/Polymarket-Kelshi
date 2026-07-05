"""Verify everything verifiable right now: breakers (synthetic), conviction cap,
cancel_order (live, $0), NWS Austin data flow, fills() endpoint."""
import sys, os, json, datetime as dt
from pathlib import Path
sys.path.insert(0, r"D:\Polymarket-Kelshi")
os.chdir(r"D:\Polymarket-Kelshi")
results = {}

# ---------- 1) circuit breakers (synthetic) ----------
from src import engine
cfg_risk = {"risk": {"max_per_trade_usd": 25, "max_daily_risk_usd": 100,
                     "max_total_exposure_usd": 300, "max_open_positions": 16,
                     "daily_loss_halt_usd": 5}}
veto = engine.check_risk({"realized_pnl_today": -5.01, "risk_used_today": 0,
                          "open_exposure": 0, "open_positions": 0}, 0.5, cfg_risk)
results["日亏熔断(-$5)"] = "PASS" if veto and "circuit breaker" in veto else f"FAIL: {veto}"
veto2 = engine.check_risk({"realized_pnl_today": -4.99, "risk_used_today": 0,
                           "open_exposure": 0, "open_positions": 0}, 0.5, cfg_risk)
results["熔断线内不误触"] = "PASS" if veto2 is None else f"FAIL: {veto2}"

# ---------- 2) favorites drawdown-step counter (synthetic) ----------
import src.ledger as ledger
ledger.DB = Path(r"C:\Users\xuboh\AppData\Local\Temp\claude\D--Polymarket-Kelshi\acd916af-5be2-415e-97cc-68147374adb7\scratchpad\test_dd.db")
if ledger.DB.exists(): ledger.DB.unlink()
for i, pnl in enumerate([-1.5, -1.6]):     # cumulative -3.1 -> step 1
    tid = ledger.insert_trade(mode="live", ticker=f"TEST-{i}", title="favorite TEST",
                              side="yes", price=0.9, contracts=2, cost_usd=1.8, fee_usd=0.02,
                              q_claude=0.9, q_codex=0.9, q_consensus=0.9, market_prob=0.9,
                              edge_net=0, rationale="t", status="open")
    ledger.settle_trade(tid, "no", pnl)
realized = ledger.realized_by_title("favorite")
step = int((-realized) // 3.0) if realized < 0 else 0
results["回撤分段计数(-$3.1→step1)"] = "PASS" if (realized == -3.1 and step == 1) else f"FAIL: {realized},{step}"
hard = step >= 5
results["硬停判定(step1<5不停)"] = "PASS" if not hard else "FAIL"

# ---------- 3) high-conviction tier (synthetic) ----------
sys.path.insert(0, r"D:\Polymarket-Kelshi\src")
from src.pipeline import _conviction_cap
class D: pass
d = D(); d.edge_net = 0.12; d.side = "yes"
cfg_hc = {"live": {"high_conviction_max_usd": 4.0,
                   "high_conviction": {"min_edge": 0.10, "max_family_divergence": 0.05,
                                       "require_all_estimators": True}}}
item_good = {"q_claude": 0.62, "q_codex": 0.60, "q_all": [0.61, 0.63, 0.58, 0.62]}
item_split = {"q_claude": 0.62, "q_codex": 0.60, "q_all": [0.61, 0.63, 0.45, 0.62]}
c1 = _conviction_cap(item_good, d, 0.50, cfg_hc)
c2 = _conviction_cap(item_split, d, 0.50, cfg_hc)
d.edge_net = 0.08
c3 = _conviction_cap(item_good, d, 0.50, cfg_hc)
results["极确档: 全同向+高边际→放行$4"] = "PASS" if c1 == 4.0 else f"FAIL: {c1}"
results["极确档: 一人反向→拒绝"] = "PASS" if c2 is None else f"FAIL: {c2}"
results["极确档: 边际不足→拒绝"] = "PASS" if c3 is None else f"FAIL: {c3}"

# ---------- 4) cancel_order (live, zero-cost) ----------
from src.live import KalshiLive
from src.kalshi_client import KalshiPublic, normalize_market
live = KalshiLive(); api = KalshiPublic()
placed = None
for series in ("KXBTCD", "KXETHD"):
    page = api._get("/markets", series_ticker=series, status="open", limit=50)
    for mr in page.get("markets", []):
        m = normalize_market(mr)
        if m["status"] == "active" and m["yes_ask"] and m["yes_ask"] > 0.10:
            # resting bid at 2c: far from ask, will never fill instantly
            resp = live.place_limit(m["ticker"], "yes", 1, 0.02, tif="good_till_canceled")
            oid = str(resp.get("order_id") or "")
            f = int(float(resp.get("fill_count") or resp.get("fill_count_fp") or 0))
            placed = (m["ticker"], oid, f)
            break
    if placed: break
if placed and placed[1] and placed[2] == 0:
    try:
        live.cancel_order(placed[1])
        o = live._req("GET", f"/trade-api/v2/portfolio/orders/{placed[1]}")
        st = (o.get("order") or {}).get("status", "?")
        results["撤单cancel_order"] = "PASS" if st in ("canceled", "cancelled") else f"状态={st}"
    except Exception as e:
        results["撤单cancel_order"] = f"FAIL: {e}"
elif placed and placed[2] > 0:
    results["撤单cancel_order"] = "SKIP: 2c竟然成交了(不可能)"
else:
    results["撤单cancel_order"] = "SKIP: 无可挂单市场"

# ---------- 5) fills() endpoint (query-param signing fix) ----------
try:
    f = live.fills(limit=3)
    n = len(f.get("fills", []))
    results["fills接口(带参签名)"] = f"PASS ({n}条流水)" if n >= 1 else "FAIL: 空"
except Exception as e:
    results["fills接口(带参签名)"] = f"FAIL: {e}"

# ---------- 6) NWS Austin (KAUS) data flow ----------
from src.weather import observed_max_f, forecast_remaining_max_f
now = dt.datetime.now(dt.timezone.utc)
mid_local = (now - dt.timedelta(hours=5)).replace(hour=0, minute=0, second=0, microsecond=0)
mid_utc = mid_local + dt.timedelta(hours=5)
obs = observed_max_f("KAUS", mid_utc)
fc = forecast_remaining_max_f(30.183, -97.680, now, mid_utc + dt.timedelta(hours=24))
ok = (obs is not None and 40 < obs < 120) or (fc is not None and 40 < fc < 120)
results["Austin KAUS 气象数据流"] = (f"PASS (观测max={obs}, 预报max={fc})" if ok
                                    else f"FAIL: obs={obs} fc={fc}")

print(json.dumps(results, ensure_ascii=False, indent=1))
