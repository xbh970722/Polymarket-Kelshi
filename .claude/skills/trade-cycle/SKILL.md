---
name: trade-cycle
description: Run one full Kalshi research + paper-trading cycle - scan markets, gather intel with agent-reach/web-access, run the dual-model debate with Codex, let the engine decide, settle, and report. Use when the user says "run trade cycle", "跑一轮", "交易循环", "daily cycle", or asks to update the paper portfolio.
---

# Trade Cycle

One full cycle of the Kalshi dual-model paper-trading pipeline in `D:\Polymarket-Kelshi`.
Follow `research/PROTOCOL.md` exactly — it is the source of truth for the research discipline.

## Steps

1. **Settle first** — resolve anything that closed since last run:
   `python -m src.pipeline settle`
2. **Scan**: `python -m src.pipeline scan` then read `data/candidates.json`.
3. **Pick up to N markets** (N = `research.markets_per_cycle` in config.yaml, default 3).
   Prefer: highest score, categories you haven't already got open positions in,
   and markets where information advantage is plausible (data releases, scheduled events).
4. **For each picked market**, follow PROTOCOL.md:
   a. `python -m src.pipeline rules TICKER` — read resolution rules verbatim.
   b. Intel via agent-reach / web-access skills (primary sources, timestamps).
   c. Blind estimate (yours) BEFORE looking at market price.
   d. Codex blind estimate via `codex exec` (background, xhigh takes minutes — launch all
      markets' round-1 calls in parallel, then collect).
   e. Round-2 debate: exchange estimates + market price, both sides update with reasons.
5. **Write** `reports/research_<YYYY-MM-DD>.json` (schema in PROTOCOL.md).
6. **Decide**: `python -m src.pipeline decide --research reports/research_<date>.json`
   — the engine and risk limits make the call, not you.
7. **Report**: `python -m src.pipeline report`, then send the report file to the user
   with a 3-line summary: new orders / settlements / calibration status.
8. **Archive**: commit and push the audit trail:
   `git add -A` then commit `cycle <date>: <n> orders, <m> settled, <k> flagged` and
   `git push`. The GitHub repo (xbh970722/Polymarket-Kelshi, private) is the wetware's
   remote console — reports must land there even when nothing traded.

## Escalation to the human (wetware protocol)

The user's role is judgment, not monitoring. Interrupt them (PushNotification if
available, otherwise lead the summary with it) ONLY when:

- new paper orders were placed (count + tickers + one-line why),
- a market was skipped for model divergence > 0.10 — this is a judgment request:
  put both estimates and the crux of disagreement in the report under
  "needs human judgment",
- any risk cap or the daily-loss circuit breaker triggered,
- the live-gate status changed (any direction),
- the cycle failed and could not complete.

A routine no-trade cycle is NOT notification-worthy — the pushed report is the record.

## Guardrails

- NEVER edit `risk:` or `live_gate:` values in config.yaml. If a limit blocks a trade,
  that is the system working — report it, don't tune it.
- NEVER set `mode: live`. The pipeline refuses it by design; going live is a joint
  decision with the user after the live gate passes.
- If model divergence > 0.10 on a market, the engine skips it — list it in your summary
  under "needs human judgment" with both estimates and one line on where the disagreement is.
- If codex exec fails or times out, record `q_codex = null`, skip that market (engine
  needs both estimates), and note it in the summary.
