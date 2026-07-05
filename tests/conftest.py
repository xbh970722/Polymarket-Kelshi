# These files are SCRIPT-STYLE live verification batteries (module-level code
# that hits the real Kalshi API and checks the real balance), written by the
# review crews as one-shot checks. They are NOT pytest tests — collecting them
# with `pytest tests/` EXECUTES live API calls at import time (found 2026-07-05:
# test_failures.py's env poisoning leaked into test_verification_battery.py's
# collection and errored the whole run). Run them deliberately, one at a time:
#     python tests/test_failures.py
collect_ignore = [
    "test_failures.py",
    "test_ledger_live.py",
    "test_r3_fixes.py",
    "test_swing.py",
    "test_verification_battery.py",
]
