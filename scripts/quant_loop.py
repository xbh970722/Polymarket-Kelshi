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
        out += run_cmd("shortcycle")
        out += run_cmd("weather")
        if nxt.minute == 20:
            out += run_cmd("manage")
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
