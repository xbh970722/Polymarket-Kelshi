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
import time

ROOT = r"D:\Polymarket-Kelshi"
LOG = os.path.join(ROOT, "data", "quant_loop.log")
PIDF = os.path.join(ROOT, "data", "quant_loop.pid")
MARKS = (5, 11, 20, 26, 35, 41, 50, 56)   # :11/:26/:41/:56 hit each 15m window at tau~4min
LAST_HOURLY = None                         # elapsed-time tracker for manage/reconcile/janitor


def log(msg: str) -> None:
    line = f"[{dt.datetime.now():%m-%d %H:%M:%S}] {msg}\n"
    try:                                    # R3-CODEX-8 MED: disk-full on the log
        with open(LOG, "a", encoding="utf-8") as f:   # must not kill the loop
            f.write(line)
    except OSError:
        return
    try:                                    # crude rotation
        if os.path.getsize(LOG) > 400_000:
            with open(LOG, encoding="utf-8") as f:
                tail = f.readlines()[-2000:]
            with open(LOG, "w", encoding="utf-8") as f:
                f.writelines(tail)
    except OSError:
        pass


def _pid_is_quant_loop(pid: int) -> bool:
    """CODEX-3 HIGH fix: PID reuse could make any python.exe look like a live loop
    and suppress restarts forever — verify the command line actually runs this script."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
            capture_output=True, text=True, timeout=20).stdout or ""
        return "quant_loop.py" in out
    except Exception:
        return False


def already_running() -> bool:
    if not os.path.exists(PIDF):
        return False
    try:
        pid = int(open(PIDF).read().strip())
        return _pid_is_quant_loop(pid)
    except Exception:
        return False


def acquire_lock() -> bool:
    """Atomic single-instance lock (OPUS-B fix): O_CREAT|O_EXCL beats the old
    check-then-write race where two loops starting in the same second both won."""
    lockf = PIDF + ".lock"
    try:
        fd = os.open(lockf, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        # stale lock? valid only if the pid inside is a live quant_loop
        try:
            content = open(lockf).read().strip()
            if content.isdigit() and _pid_is_quant_loop(int(content)):
                return False
            # CODEX-3 MED fix: malformed/empty lock (crash before write) recovers
            # by mtime instead of failing closed forever
            if not content.isdigit():
                age_min = (dt.datetime.now().timestamp() - os.path.getmtime(lockf)) / 60
                if age_min < 10:
                    return False
            os.remove(lockf)
            return acquire_lock()
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
    """OPUS-B fix: pushes used to fail silently on non-fast-forward (concurrent
    Claude-session commits) and the remote diverged. Now: detect, rebase, retry."""
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True,
                           timeout=120, cwd=ROOT)
        if args[0] == "push" and r.returncode != 0:
            # CODEX-3 HIGH fix: never leave the repo mid-rebase with a binary ledger.
            # Merge (not rebase) preferring OUR files — the local ledger is the source
            # of truth — and clean up hard if the merge itself fails.
            log(f"git push rejected: {(r.stderr or '')[:150]} -> merge -X ours + retry")
            m = subprocess.run(["git", "pull", "--no-rebase", "--no-edit", "-X", "ours"],
                               capture_output=True, text=True, timeout=120, cwd=ROOT)
            if m.returncode != 0:
                subprocess.run(["git", "merge", "--abort"], capture_output=True,
                               text=True, timeout=60, cwd=ROOT)
                log(f"git merge failed and aborted: {(m.stderr or '')[:150]} "
                    "(will retry next mark)")
                return
            r2 = subprocess.run(["git", "push"], capture_output=True, text=True,
                                timeout=120, cwd=ROOT)
            log("git push retry " + ("ok" if r2.returncode == 0
                                     else f"FAILED: {(r2.stderr or '')[:150]}"))
    except Exception as e:
        log(f"git {args} failed: {e}")


REVIEW_STATE = os.path.join(ROOT, "data", "review_state.json")
REVIEW_DUE = os.path.join(ROOT, "data", "review_due_shortcycle.json")


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
            try:
                state = json.load(open(REVIEW_STATE, encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # OPUS-B fix: torn read mid-rewrite -> skip this tick, never default
                # last_review_id=0. R3-CODEX-2 MED refinement: PERSISTENT corruption
                # (>30min old) would disable loss reviews forever — self-heal by
                # rebuilding at the current max id (no re-fire, reviews resume).
                try:
                    if (time.time() - os.path.getmtime(REVIEW_STATE)) / 60 > 30:
                        os.replace(REVIEW_STATE, REVIEW_STATE + ".corrupt")
                        con_h = sqlite3.connect(os.path.join(ROOT, "data", "ledger.db"))
                        max_id = con_h.execute(
                            "SELECT COALESCE(MAX(id),0) FROM trades").fetchone()[0]
                        con_h.close()
                        state = {"last_review_id": max_id, "review_no": 0}
                        json.dump(state, open(REVIEW_STATE, "w", encoding="utf-8"))
                        log(f"CRITICAL: review_state.json corrupt >30min -> rebuilt "
                            f"at id {max_id} (old file kept as .corrupt)")
                    else:
                        return
                except Exception:
                    return
        if os.path.exists(REVIEW_DUE):        # pending review; respect cooldown
            # R3-CODEX-4 MED: epoch math, immune to DST wall-clock jumps
            age_h = (time.time() - os.path.getmtime(REVIEW_DUE)) / 3600
            if age_h < cr.get("cooldown_hours", 2):
                return
        con = sqlite3.connect(os.path.join(ROOT, "data", "ledger.db"))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, pnl_usd FROM trades WHERE id > ? AND mode='live' "
            "AND status IN ('settled','closed') AND pnl_usd < 0 "
            "AND title LIKE 'shortcycle%'",   # CODEX-6 MED: scope by LANE title —
            # favorites losses have their own drawdown cadence; ticker prefixes
            # collide across lanes (XRP blindness fixed via title too)
            (state.get("last_review_id", 0),)).fetchall()
        n_loss = len(rows)
        usd_loss = -sum(r["pnl_usd"] for r in rows)
        if n_loss < cr.get("loss_count_trigger", 5) and usd_loss < cr.get("loss_usd_trigger", 1.0):
            return
        # OPUS-B fix: lane-specific file so a favorites drawdown trigger and this
        # crypto trigger can never clobber each other in a shared review_due.json
        json.dump({"triggered_ts": dt.datetime.now().isoformat(timespec="seconds"),
                   "lane": "shortcycle",
                   "n_losses": n_loss, "usd_loss": round(usd_loss, 2),
                   "since_id": state.get("last_review_id", 0)},
                  open(os.path.join(ROOT, "data", "review_due_shortcycle.json"),
                       "w", encoding="utf-8"))
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
    aged 3-16h whose start minute matches task-launch minutes. The <16h upper
    bound protects long-lived interactive sessions (review 2026-07-04: a
    days-old chat session could otherwise collide on start-minute)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process claude -ErrorAction SilentlyContinue | "
             "Where-Object { $h = ((Get-Date) - $_.StartTime).TotalHours; "
             "$h -gt 3 -and $h -lt 16 -and "
             # R3-FABLE MED: cover the real jittered launch windows — daily-cycle
             # 0-8, blind-AI 12-16, supervisor 20-22, reflection 30-40
             "$_.StartTime.Minute -in (0..16 + 20..22 + 30..40) } | "
             "ForEach-Object { Stop-Process -Id $_.Id -Force; $_.Id }"],
            capture_output=True, text=True, timeout=60)
        killed = [x for x in (out.stdout or "").split() if x.strip().isdigit()]
        if killed:
            log(f"janitor: killed stale task sessions {killed}")
    except Exception as e:
        log(f"janitor failed: {e}")


def main() -> None:
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    if already_running() or not acquire_lock():
        print("quant_loop already running; exiting")
        return
    open(PIDF, "w").write(str(os.getpid()))
    import atexit

    def _release_lock():
        # CODEX-3 HIGH fix: only remove the lock if WE still own it — an exiting
        # old loop must never delete a new loop's fresh lock (double-loop risk)
        lockf = PIDF + ".lock"
        try:
            if os.path.exists(lockf) and open(lockf).read().strip() == str(os.getpid()):
                os.remove(lockf)
        except Exception:
            pass
    atexit.register(_release_lock)
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
        # CODEX-3 HIGH fix: hourly duties run on elapsed time, not an exact minute —
        # a mark overrun past :20 no longer skips exits/reconcile for the whole hour.
        # R3-CODEX-4 HIGH: monotonic clock, immune to DST wall-clock jumps.
        global LAST_HOURLY
        mono = time.monotonic()
        if LAST_HOURLY is None or (mono - LAST_HOURLY) >= 3540:
            LAST_HOURLY = mono
            out += run_cmd("manage")
            out += run_cmd("reconcile")   # books-vs-exchange audit; MISMATCH lines
                                          # land in the log/journal for the reflection
            janitor_stale_sessions()      # scheduled-task claude sessions leak ~370MB each
        changed = any(k in out for k in ("SETTLED", "LIVE ", "EXIT ", "REVIEW-DUE",
                                         "MISMATCH", "UNKNOWN", "VOIDED", "RESOLVED",
                                         "CRITICAL", "FAILED", "REJECTED"))
        if changed:
            run_cmd("journal")
            run_cmd("report")
            git("add", "-A")
            git("commit", "-m", f"quant loop {nxt:%m-%d %H:%M}: auto fills/settlements")
            git("push")
            log("committed + pushed")


if __name__ == "__main__":
    main()
