"""Resident quant loop: pure Python, no LLM. Runs the mechanical lanes every
15 minutes (:05 :20 :35 :50) so the 15-minute markets get hit inside every window.

    settle -> shortcycle (hourly + 15m crypto) -> weather -> (manage at :20) -> journal
    -> git commit/push when anything changed

Single-instance via pid file. Survives as long as the machine is on — does not
need the Claude Code app. The hourly Claude scheduled task acts as supervisor
and restarts this loop if the log goes stale.
"""
import datetime as dt
import os
import subprocess
import sys

ROOT = r"D:\Polymarket-Kelshi"
LOG = os.path.join(ROOT, "data", "quant_loop.log")
PIDF = os.path.join(ROOT, "data", "quant_loop.pid")
MARKS = (5, 11, 20, 26, 35, 41, 50, 56)   # :11/:26/:41/:56 hit each 15m window at tau~4min


def log(msg: str) -> None:
    line = f"[{dt.datetime.now():%m-%d %H:%M:%S}] {msg}\n"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line)
    try:                                    # crude rotation
        if os.path.getsize(LOG) > 400_000:
            with open(LOG, encoding="utf-8") as f:
                tail = f.readlines()[-2000:]
            with open(LOG, "w", encoding="utf-8") as f:
                f.writelines(tail)
    except OSError:
        pass


def already_running() -> bool:
    if not os.path.exists(PIDF):
        return False
    try:
        pid = int(open(PIDF).read().strip())
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True, timeout=15).stdout
        return str(pid) in out and "python" in out.lower()
    except Exception:
        return False


def run_cmd(*args: str) -> str:
    try:
        r = subprocess.run([sys.executable, "-m", "src.pipeline", *args],
                           capture_output=True, text=True, timeout=300, cwd=ROOT)
        out = (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        out = f"EXC {args}: {e}"
    for ln in out.strip().splitlines():
        log(f"  {args[0]}: {ln}")
    return out


def git(*args: str) -> None:
    try:
        subprocess.run(["git", *args], capture_output=True, text=True, timeout=120, cwd=ROOT)
    except Exception as e:
        log(f"git {args} failed: {e}")


REVIEW_STATE = os.path.join(ROOT, "data", "review_state.json")
REVIEW_DUE = os.path.join(ROOT, "data", "review_due.json")


def check_review_trigger() -> None:
    """Loss-triggered crypto review: summon a Fable 5 session when crypto losses
    since the last review hit the configured count/USD threshold."""
    import json
    import sqlite3
    try:
        import yaml
        cfg = yaml.safe_load(open(os.path.join(ROOT, "config.yaml"), encoding="utf-8"))
        cr = cfg.get("crypto_review") or {}
        if not cr.get("enabled"):
            return
        state = {"last_review_id": 0, "review_no": 0}
        if os.path.exists(REVIEW_STATE):
            state = json.load(open(REVIEW_STATE, encoding="utf-8"))
        if os.path.exists(REVIEW_DUE):        # pending review; respect cooldown
            age_h = (dt.datetime.now()
                     - dt.datetime.fromtimestamp(os.path.getmtime(REVIEW_DUE))).total_seconds() / 3600
            if age_h < cr.get("cooldown_hours", 2):
                return
        con = sqlite3.connect(os.path.join(ROOT, "data", "ledger.db"))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, pnl_usd FROM trades WHERE id > ? AND mode='live' "
            "AND status IN ('settled','closed') AND pnl_usd < 0 AND ("
            "ticker LIKE 'KXBTC%' OR ticker LIKE 'KXETH%' OR ticker LIKE 'KXSOL%')",
            (state.get("last_review_id", 0),)).fetchall()
        n_loss = len(rows)
        usd_loss = -sum(r["pnl_usd"] for r in rows)
        if n_loss < cr.get("loss_count_trigger", 5) and usd_loss < cr.get("loss_usd_trigger", 1.0):
            return
        json.dump({"triggered_ts": dt.datetime.now().isoformat(timespec="seconds"),
                   "n_losses": n_loss, "usd_loss": round(usd_loss, 2),
                   "since_id": state.get("last_review_id", 0)},
                  open(REVIEW_DUE, "w", encoding="utf-8"))
        # NOTE: the loop does NOT spawn a headless claude (nested -p proved unreliable).
        # It only RAISES the flag; the hourly app-scheduled supervisor task detects
        # data/review_due.json and performs the Fable 5 review — that path actually runs.
        log(f"REVIEW TRIGGERED: {n_loss} crypto losses / ${usd_loss:.2f} since review "
            f"#{state.get('review_no', 0)} -> review_due.json raised for supervisor")
    except Exception as e:
        log(f"review trigger check failed: {e}")


def janitor_stale_sessions() -> None:
    """Scheduled-task claude sessions don't exit and leak ~370MB each (found
    2026-07-04: pagefile exhaustion, fork failures). Kill 'claude' processes
    older than 3h whose start minute matches task-launch minutes — interactive
    sessions rarely start exactly then, task sessions always do."""
    try:
        import psutil  # optional; skip silently if unavailable
    except ImportError:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Process claude -ErrorAction SilentlyContinue | "
                 "Where-Object { ((Get-Date) - $_.StartTime).TotalHours -gt 3 -and "
                 "$_.StartTime.Minute -in 20,21,22,40,44,45,46,56 } | "
                 "ForEach-Object { Stop-Process -Id $_.Id -Force; $_.Id }"],
                capture_output=True, text=True, timeout=60)
            killed = [x for x in (out.stdout or "").split() if x.strip().isdigit()]
            if killed:
                log(f"janitor: killed stale task sessions {killed}")
        except Exception as e:
            log(f"janitor failed: {e}")
        return


def main() -> None:
    if already_running():
        print("quant_loop already running; exiting")
        return
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    open(PIDF, "w").write(str(os.getpid()))
    log(f"=== quant_loop started pid={os.getpid()} ===")
    while True:
        now = dt.datetime.now()
        future = [now.replace(minute=m, second=20, microsecond=0)
                  for m in MARKS if now.replace(minute=m, second=20, microsecond=0) > now]
        nxt = future[0] if future else (now + dt.timedelta(hours=1)).replace(
            minute=MARKS[0], second=20, microsecond=0)
        wait = (nxt - now).total_seconds()
        if wait > 0:
            import time
            time.sleep(wait)
        out = run_cmd("settle")
        check_review_trigger()
        run_cmd("mktsnap")          # zero-cost calibration sampling (H5, never trades)
        out += run_cmd("shortcycle")
        out += run_cmd("favorites")  # favorite-harvest micro lane (direction-neutral)
        out += run_cmd("weather")
        if nxt.minute == 20:
            out += run_cmd("manage")
            out += run_cmd("reconcile")   # hourly books-vs-exchange audit; MISMATCH lines
                                          # land in the log/journal for the reflection to flag
            janitor_stale_sessions()      # scheduled-task claude sessions leak ~370MB each
        changed = any(k in out for k in ("SETTLED", "LIVE ", "EXIT "))
        if changed:
            run_cmd("journal")
            run_cmd("report")
            git("add", "-A")
            git("commit", "-m", f"quant loop {nxt:%m-%d %H:%M}: auto fills/settlements")
            git("push")
            log("committed + pushed")


if __name__ == "__main__":
    main()
