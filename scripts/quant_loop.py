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
LIGHT_MARKS = (0, 2, 8, 15, 17, 23, 30, 32, 38, 45, 47, 53)   # 15m-only passes
# (user 2026-07-05 ×2): timing study — 15m edge is MONOTONE in tau (+5.5pt at
# tau 2-4 -> +11.6pt at 12-14), so :00/:15/:30/:45 add the earliest look
# (tau~14.7, fattest bin) on top of ~12.7/9.7/6.7. Four scans per window.
# (h15+h10 only, ~5 API calls) — each 15m window now gets THREE entry-window
# scans (tau ~12.7/9.7/6.7) instead of one, tripling the catch rate on
# transient zone asks; h15 fill-detection latency drops from ~7.5 to ~3 min.
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


_TREE_MODULES = ["src/pipeline.py", "src/ledger.py", "src/live.py", "src/engine.py",
                 "src/shortcycle.py", "src/weather.py", "src/kalshi_client.py",
                 "src/h10.py", "src/disloc.py", "src/pmwatch.py", "src/wxfade.py",
                 "src/blindai.py", "src/mktcal.py"]   # R7-C5: ALL hot-loaded modules


def tree_healthy() -> bool:
    """R4-FABLE-B MED: the loop hot-loads the working tree every mark — a
    half-saved edit must skip the mark LOUDLY, not fail every lane quietly."""
    try:
        r = subprocess.run([sys.executable, "-m", "py_compile", *_TREE_MODULES],
                           capture_output=True, text=True, timeout=60, cwd=ROOT)
        if r.returncode != 0:
            log(f"CRITICAL: working tree does not compile - SKIPPING mark "
                f"({(r.stderr or '')[:200]})")
            return False
        return True
    except Exception as e:
        log(f"tree health check errored ({e}) - proceeding")
        return True


def run_cmd(*args: str, timeout: int = 300) -> str:
    """R7-C5: collectors get short leashes — a hanging shadow step must never
    eat the mark budget that the money lanes (h15 cancel discipline!) need."""
    try:
        r = subprocess.run([sys.executable, "-m", "src.pipeline", *args],
                           capture_output=True, text=True, timeout=timeout,
                           cwd=ROOT)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            log(f"CRITICAL: step {args[0]} exited {r.returncode}")
            out += f"\nCRITICAL step {args[0]} exited {r.returncode}"
            # R9-C2: the synthetic CRITICAL must reach the caller's `out`
            # so failures trigger journal/commit like any other event
    except Exception as e:
        out = f"EXC {args}: {e}"
        log(f"CRITICAL: step {args[0]} raised/timed out: {e}")
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
        # R6-FABLE governance: weather loss trigger — placed BEFORE the crypto
        # cooldown early-return (R7-C5 MED: it used to sit below it, so a pending
        # shortcycle review inside cooldown would blind the weather tripwire).
        try:
            wstate_p = os.path.join(ROOT, "data", "weather_review_state.json")
            wdue_p = os.path.join(ROOT, "data", "review_due_weather.json")
            wstate = {"last_review_id": 0}
            if os.path.exists(wstate_p):
                wstate = json.load(open(wstate_p, encoding="utf-8"))
            if not os.path.exists(wdue_p):
                wcon = sqlite3.connect(os.path.join(ROOT, "data", "ledger.db"))
                wcon.row_factory = sqlite3.Row
                wrows = wcon.execute(
                    "SELECT id, pnl_usd FROM trades WHERE id > ? AND mode='live' "
                    "AND status IN ('settled','closed') AND title LIKE 'weather%' "
                    "ORDER BY id",
                    (wstate.get("last_review_id", 0),)).fetchall()
                wcon.close()
                cum = sum(r["pnl_usd"] or 0 for r in wrows)
                streak = 0
                for r in reversed(wrows):
                    if (r["pnl_usd"] or 0) < 0:
                        streak += 1
                    else:
                        break
                if cum <= -2.0 or streak >= 4:
                    json.dump({"triggered_ts": dt.datetime.now().isoformat(timespec="seconds"),
                               "lane": "weather", "cum_pnl": round(cum, 2),
                               "consec_losses": streak,
                               "since_id": wstate.get("last_review_id", 0)},
                              open(wdue_p, "w", encoding="utf-8"))
                    log(f"WEATHER REVIEW TRIGGERED: cum ${cum:.2f}, "
                        f"streak {streak} -> review_due_weather.json")
        except Exception as e:
            log(f"weather trigger check failed: {e}")
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
    """Leaked claude-code session backends eat ~130-370MB each plus ~5 MCP
    child servers (~180MB) — found 2026-07-04 as pagefile exhaustion; audit
    2026-07-05 found 14 leftovers aged 24-44h that the old start-minute
    heuristic missed (they were parented by the desktop app, and >16h fell
    outside the window). Two rules, both PID-recycling-safe:
      (a) ORPHAN: CLI session whose parent is dead or was created AFTER it
          (Windows recycles PIDs; existence alone lies), age >3h — classic
          schtasks leak, any start minute.
      (b) IDLE LEFTOVER: parent alive (desktop-app-spawned) but age >16h AND
          lifetime CPU <20min — a finished task session idling for a day.
          The CPU floor protects genuinely active marathons (a live user
          session accumulates hours of CPU); transcripts persist on disk,
          so a killed backend just respawns if its session is reopened.
    Desktop app itself (--type= electron children / non-CLI) never touched."""
    ps = (
        "$all = Get-CimInstance Win32_Process; $byPid = @{}; "
        "foreach ($p in $all) { $byPid[[int]$p.ProcessId] = $p }; "
        "$now = Get-Date; "
        "foreach ($p in $all) { "
        "if ($p.Name -ne 'claude.exe') { continue }; "
        "$cl = $p.CommandLine; "
        "if (-not $cl -or $cl -notmatch 'claude-code' -or $cl -match '--type=') { continue }; "
        "$age = ($now - $p.CreationDate).TotalHours; "
        "if ($age -lt 3) { continue }; "
        "$par = $byPid[[int]$p.ParentProcessId]; "
        "$orphan = ($null -eq $par -or $par.CreationDate -gt $p.CreationDate); "
        "$idle = $false; "
        "if (-not $orphan -and $age -gt 16) { "
        "$gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue; "
        "if ($gp -and $gp.TotalProcessorTime.TotalMinutes -lt 20) { $idle = $true } }; "
        "if ($orphan -or $idle) { "
        "try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; $p.ProcessId } catch {} } }"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=90)
        killed = [x for x in (out.stdout or "").split() if x.strip().isdigit()]
        if killed:
            log(f"janitor: reaped leaked sessions {killed}")
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
        slots = ([(m, "full") for m in MARKS]
                 + [(m, "light") for m in LIGHT_MARKS])
        future = []
        # R8-O2: timing jitter — fixed second=20 made every order land in a
        # 3-second window (:XX:20-22): a metronome any observer can front-run.
        # R9-C2: jitter is derived PER SLOT (hash is process-seeded => stable
        # within this run, unpredictable across restarts) so re-waking inside
        # a target minute cannot re-roll the second and skip the mark.
        for m, kind in slots:
            jit = 8 + (hash((now.date(), m, kind)) % 45)
            t = now.replace(minute=m, second=0, microsecond=0) \
                + dt.timedelta(seconds=jit)
            if t > now:
                future.append((t, kind))
        if future:
            nxt, kind = min(future)
        else:
            nxt = (now + dt.timedelta(hours=1)).replace(
                minute=LIGHT_MARKS[0], second=20, microsecond=0)
            kind = "light"
        wait = (nxt - now).total_seconds()
        if wait > 0:
            time.sleep(wait)
        if not tree_healthy():     # R4-FABLE-B: never trade a broken working tree
            continue
        if kind == "light":        # 15m pass: h15 lifecycle + h10 scan + stop guard
            out = run_cmd("h15", timeout=120)
            out += run_cmd("h10", timeout=120)
            out += run_cmd("stopshadow", timeout=60)   # live dual-condition stop:
            #  densest cadence = shortest death-detection latency (~2-3 min)
            if any(k in out for k in ("LIVE ", "H15 ", "EXIT ", "UNKNOWN",
                                      "CRITICAL", "HARD STOP")):
                run_cmd("journal")
                git("add", "data", "reports")   # R8-C2: whitelist — never sweep code
                git("commit", "-m",
                    f"light mark {nxt:%m-%d %H:%M}: 15m fills")
                git("push")
                log("light mark committed + pushed")
            continue
        out = run_cmd("settle")
        # R7-C4/C5: h15 FIRST after settle — its cancel/fill management is the
        # most time-critical money path; a slow collector must never delay it.
        # (Also gives the maker experiment priority over h10's taker on the
        # shared one-15m-position mutex — R7-C2.)
        out += run_cmd("h15", timeout=120)
        # R8-C2 HIGH: stop guard runs IMMEDIATELY after h15 — behind the
        # collectors it could inherit 10+ min of their worst-case timeouts,
        # which is exactly the latency a stop must not have.
        out += run_cmd("stopshadow", timeout=60)
        check_review_trigger()
        run_cmd("mktsnap", timeout=60)   # zero-cost calibration sampling (H5)
        out += run_cmd("shortcycle")
        out += run_cmd("favorites")  # favorite-harvest micro lane (direction-neutral)
        out += run_cmd("h10", timeout=120)   # 15m shadow + capped probe (R6)
        out += run_cmd("weather")
        # (stopshadow moved up right after h15 — R8-C2)
        run_cmd("disloc", timeout=60)        # H12 dislocation shadow
        run_cmd("pmwatch", timeout=60)       # H14 Polymarket pairs (read-only)
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
            run_cmd("wxfade")             # W2 fade shadow (hourly is plenty: tau 8-48h)
            janitor_stale_sessions()      # scheduled-task claude sessions leak ~370MB each
        changed = any(k in out for k in ("SETTLED", "LIVE ", "EXIT ", "REVIEW-DUE",
                                         "MISMATCH", "UNKNOWN", "VOIDED", "RESOLVED",
                                         "CRITICAL", "FAILED", "REJECTED", "H15 ",
                                         "HARD STOP", "DRAWDOWN REVIEW",
                                         "EXC ", "STOPSHADOW", "STOPGUARD"))
        if changed:
            run_cmd("journal")
            run_cmd("report")
            git("add", "data", "reports")   # R8-C2: whitelist — never sweep code
            git("commit", "-m", f"quant loop {nxt:%m-%d %H:%M}: auto fills/settlements")
            git("push")
            log("committed + pushed")


if __name__ == "__main__":
    main()
