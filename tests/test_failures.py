"""Failure-path battery: every test here is SUPPOSED to fail — the pass criterion
is that failure is clean (clear error, no crash, no phantom ledger entry, no money)."""
import sys, os, json, subprocess
sys.path.insert(0, r"D:\Polymarket-Kelshi")
os.chdir(r"D:\Polymarket-Kelshi")
results = {}
from src.live import KalshiLive, LiveAuthError
from src.kalshi_client import KalshiPublic, normalize_market

live = KalshiLive()
api = KalshiPublic()
bal0 = float(live.balance()["balance_dollars"])

# ---- F1: order on an already-settled market -> exchange must reject cleanly ----
try:
    r = live.place_limit("KXBTCD-26JUL0312-T61799.99", "yes", 1, 0.50)   # noon Jul-3, long settled
    results["F1 已结算市场下单"] = f"异常: 竟然被接受了 {json.dumps(r)[:80]}"
except RuntimeError as e:
    msg = str(e)
    results["F1 已结算市场下单"] = ("PASS: 干净拒绝 - " + msg[:90]) if "HTTP" in msg else f"FAIL: {msg[:90]}"
except Exception as e:
    results["F1 已结算市场下单"] = f"FAIL: 崩溃类型 {type(e).__name__}: {e}"

# ---- F2: order far beyond balance -> insufficient funds rejection ----
target = None
for series in ("KXBTCD", "KXETHD"):
    page = api._get("/markets", series_ticker=series, status="open", limit=50)
    for mr in page.get("markets", []):
        m = normalize_market(mr)
        if m["status"] == "active" and m["yes_ask"] and 0.3 <= m["yes_ask"] <= 0.95:
            target = m["ticker"]; ask = m["yes_ask"]; break
    if target: break
if target:
    try:
        r = live.place_limit(target, "yes", 999, ask)     # ~$500+ >> balance ~$15
        filled = int(float(r.get("fill_count") or r.get("fill_count_fp") or 0))
        results["F2 超余额下单(999张)"] = (f"异常: 接受且成交{filled}张!" if filled
                                          else f"部分接受未成交, order={r.get('order_id','?')[:8]}")
        oid = r.get("order_id")
        if oid and not filled:
            try: live.cancel_order(str(oid))
            except Exception: pass
    except RuntimeError as e:
        results["F2 超余额下单(999张)"] = "PASS: 干净拒绝 - " + str(e)[:90]
else:
    results["F2 超余额下单(999张)"] = "SKIP: 无活跃市场"

# ---- F3: reduce-only exit on a position we don't hold ----
if target:
    try:
        r = live.place_exit(target, "yes", 1, 0.30)
        filled = int(float(r.get("fill_count") or r.get("fill_count_fp") or 0))
        results["F3 卖出未持有仓位(reduce_only)"] = ("PASS: 0成交(reduce_only兜住)" if not filled
                                                     else f"异常: 成交了{filled}张!")
    except RuntimeError as e:
        results["F3 卖出未持有仓位(reduce_only)"] = "PASS: 干净拒绝 - " + str(e)[:90]

# ---- F4: bad credentials -> LiveAuthError (not a crash) ----
env_backup = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
os.environ["KALSHI_PRIVATE_KEY_PATH"] = r"C:\nonexistent\fake.pem"
os.environ["KALSHI_API_KEY_ID"] = "fake-id"
import importlib
import src.live as live_mod
try:
    KalshiLive2 = live_mod.KalshiLive
    # force re-read: patch _SECRETS_DIR so file fallback also misses
    old_dir = live_mod._SECRETS_DIR
    live_mod._SECRETS_DIR = r"C:\nonexistent"
    try:
        KalshiLive2()
        results["F4 坏凭据"] = "FAIL: 未抛 LiveAuthError"
    except LiveAuthError as e:
        results["F4 坏凭据"] = "PASS: LiveAuthError - " + str(e)[:60]
    except Exception as e:
        results["F4 坏凭据"] = f"FAIL: 错误类型 {type(e).__name__}"
    finally:
        live_mod._SECRETS_DIR = old_dir
finally:
    if env_backup: os.environ["KALSHI_PRIVATE_KEY_PATH"] = env_backup
    os.environ.pop("KALSHI_API_KEY_ID", None)

# ---- F5: double-start the quant loop -> second instance must refuse ----
r = subprocess.run([sys.executable, "scripts/quant_loop.py"], capture_output=True,
                   text=True, timeout=30, cwd=r"D:\Polymarket-Kelshi")
out = (r.stdout or "") + (r.stderr or "")
results["F5 循环双开保护"] = ("PASS: 第二实例拒绝启动" if "already running" in out
                              else f"FAIL: {out[:90]}")

# ---- money check: all failure tests must cost $0 ----
bal1 = float(live.balance()["balance_dollars"])
results["资金零损耗"] = f"PASS (${bal0:.4f} -> ${bal1:.4f})" if abs(bal1-bal0) < 0.001 else f"FAIL: 差{bal1-bal0:+.4f}"

print(json.dumps(results, ensure_ascii=False, indent=1))
