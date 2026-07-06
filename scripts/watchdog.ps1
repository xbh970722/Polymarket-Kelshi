# Watchdog: keeps the two resident daemons alive across crashes/reboots.
# Launched at logon via an HKCU Run entry (no admin needed) in -Loop mode, so
# it self-checks forever; also runnable single-shot for manual use. Both daemons
# self-lock (quant_loop: atomic O_EXCL pid lock + cmdline verify; ws_capture:
# heartbeat pid with stale takeover), so relaunching an ALREADY-up daemon is a
# no-op — safe to fire as often as we like.
#
# Runs as the logged-in user (NOT SYSTEM) on purpose: the loop does `git push`
# every changed mark and needs the user's git credential store.
param([switch]$Loop, [int]$IntervalSec = 180)
$ErrorActionPreference = "SilentlyContinue"
$py   = "C:\Users\xuboh\AppData\Local\Programs\Python\Python312\python.exe"
$repo = "D:\Polymarket-Kelshi"
$tick = "D:\kalshi-ticks"
$wlog = "$tick\watchdog.log"

function Log($m) {
    "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss')) $m" |
        Out-File -FilePath $wlog -Append -Encoding utf8
}

# Return $true if a python process whose command line contains $needle is alive.
function Running($needle) {
    $p = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
         Where-Object { $_.CommandLine -like "*$needle*" }
    return [bool]$p
}

function Check-Once {
    # --- quant loop (money path) ---
    if (-not (Running "quant_loop.py")) {
        Start-Process -FilePath $py -ArgumentList "scripts\quant_loop.py" `
            -WorkingDirectory $repo -WindowStyle Hidden
        Log "RESTART quant_loop (was down)"
    }
    # --- tick capture daemon (data path) ---
    if (-not (Running "ws_capture.py")) {
        Start-Process -FilePath $py `
            -ArgumentList "$tick\ws_capture.py --gap-dir $tick --pid-file $tick\ws_capture_daemon.pid" `
            -WorkingDirectory $repo -WindowStyle Hidden
        Log "RESTART ws_capture (was down)"
    }
}

# single-instance guard for the watchdog LOOP itself (so the logon Run entry
# firing again on a re-logon doesn't stack a second forever-loop)
if ($Loop) {
    $lock = "$tick\watchdog.lock"
    try {
        $mine = [System.IO.File]::Open($lock, 'OpenOrCreate', 'ReadWrite', 'None')
    } catch {
        Log "another watchdog loop already holds the lock; exiting"
        return
    }
    Log "watchdog loop START (interval ${IntervalSec}s)"
    try {
        while ($true) { Check-Once; Start-Sleep -Seconds $IntervalSec }
    } finally { $mine.Close(); Remove-Item $lock -Force -ErrorAction SilentlyContinue }
} else {
    Check-Once
}
