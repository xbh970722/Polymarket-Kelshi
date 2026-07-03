---
name: trade-cycle
description: Run one full Kalshi research + trading cycle - scan markets, gather intel with agent-reach/web-access, run the 4-estimator ensemble debate (Opus x2 + Codex x2, arbiter), verify via social media and databases, let the engine decide, settle, and report. Use when the user says "run trade cycle", "跑一轮", "交易循环", "daily cycle", or asks to update the portfolio.
---

# Trade Cycle

One full cycle of the Kalshi ensemble pipeline in `D:\Polymarket-Kelshi`.
`research/PROTOCOL.md` is the source of truth for research discipline. Read config.yaml first —
models, interaction mode, verification, and live settings all come from it.

## Steps

1. **Settle first**: `python -m src.pipeline settle`
1b. **Manage open positions** (swing / VALUES.md #10): `python -m src.pipeline manage`.
    This mechanically takes profit / stops out at stored targets. For any position it
    prints as `REVIEW-DUE`, run the ensemble research flow (step 4) on that ticker with
    the ORIGINAL entry thesis in hand, then act on the fresh consensus:
    - thesis still holds with room → keep (optionally raise target via set_exit_plan);
    - fair value converged to mark → exit now (treat as a manual take-profit);
    - fair value flipped against us → exit now (thesis broken).
    Record any target change; note review outcomes in the summary.
2. **Scan**: `python -m src.pipeline scan`, read `data/candidates.json`.
3. **Pick markets** (up to `research.markets_per_cycle`):
   - Interactive session AND `interaction.ask_before_research: true` → AskUserQuestion
     (multiSelect) with the top candidates so the user chooses; offer your recommendation.
   - Scheduled/headless run → auto-pick: highest score, category diversity,
     plausible information edge, no existing open position.
4. **Ensemble research** per PROTOCOL.md (集成模式):
   a. `python -m src.pipeline rules TICKER` — read resolution rules verbatim.
   b. Intel via agent-reach / web-access / public APIs (primary sources, timestamps).
   c. Launch ALL blind estimators in parallel, models from `ensemble:` config:
      - `claude_family.count` Agent-tool subagents (model: `claude_family.model`,
        personas inside_view / outside_view, tools forbidden, market prices withheld)
      - `codex_family.count` background `codex exec -s read-only` calls
        (model `codex_family.model`, effort `codex_family.reasoning_effort`)
   d. Arbiter (this session) aggregates: family means -> q_claude / q_codex;
      pre-register sanity ranges BEFORE reading results; round-2 focused debate
      only where a crux decides trade/no-trade. Arbiter may kill, never create.
5. **Verification layer** (`verification:` in config, MANDATORY before any trade order):
   for each market that would generate an order, search the last 24h on the configured
   social channels (agent-reach: twitter/reddit) + check the relevant database
   (FRED / official calendars for econ, exchange data for crypto) for material information
   the estimators lacked. New material info → feed back to round 2 and re-decide.
   Skips don't need verification.
6. **Decide**: `python -m src.pipeline decide --research reports/research_<date>.json`
   — the engine and hard risk limits make the call, not you.
7. **Live orders** (only when mode=live + live.enabled):
   decide leaves them as PENDING. Then:
   - `live.require_confirm: true` + interactive → run the confirm-trades flow (AskUserQuestion).
   - `live.require_confirm: true` + scheduled → PushNotification "N live orders pending
     confirmation" and STOP (user confirms later via confirm-trades).
   - `live.require_confirm: false` → `python -m src.pipeline execute-live --confirmed`
     directly (user's standing auto-policy; hard limits already enforced upstream).
8. **Report**: `python -m src.pipeline report`, send the report file with a 3-line summary.
9. **Archive**: `git add -A`, commit `cycle <date>: <n> orders, <m> settled, <k> flagged`,
   `git push`. Reports must land on GitHub even when nothing traded.

## Values file (数字湿件) — 取代逐次提问

`research/VALUES.md` is the user's codified cognition (collected 2026-07-03). Consult it
every cycle; do NOT ask the user questions already covered there. Key operative rules:
- Round-2 half-anchor: after seeing the market price, a family's final may move AT MOST
  half the distance from blind consensus toward market — UNLESS verification invalidated
  round-1 facts (then re-estimate freely).
- Live auto-switch standing order: when (keys pass live-check) AND (>=15 settled paper
  trades) AND (paper P&L positive) AND (>=14 days since first paper trade), set
  mode: live + live.enabled: true + require_confirm: false, restate the new blast radius
  in the commit message, and PushNotification the user. This is the ONLY time you edit
  those switches, and the standing order in VALUES.md #5 is your authorization.
- Only ask the user when a decision type is genuinely NOT covered by VALUES.md;
  afterwards, propose adding the answer to VALUES.md.

## Escalation to the human (per VALUES.md #7)

PushNotification ONLY for: circuit breaker / streak losses, the live auto-switch event,
risk-cap saturation, cycle failure, and the SUNDAY WEEKLY REPORT (trades, settlements,
P&L, Brier trend, watchlist, any parameter amendments the system proposes).
Everything else — orders, settlements, skips, watchlist changes — lands silently in
GitHub. On Sundays, also write reports/weekly_<date>.md before pushing.

## Guardrails

- NEVER edit `risk:` values or set `live.enabled` / `live.require_confirm` yourself —
  those flips belong to the user alone (they may instruct you; then you edit, restate
  the new blast radius, commit).
- If codex fails twice, record that family as unavailable and skip the market
  (both families are required to trade).
- Model upgrades happen in config.yaml `ensemble:` only; don't hardcode model names anywhere.
