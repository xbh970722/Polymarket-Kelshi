---
name: confirm-trades
description: Review and execute (or cancel) pending live orders. Use when the user says "确认交易", "confirm trades", "pending orders", "执行挂单", or after being notified that live orders await confirmation.
---

# Confirm Trades

Work in `D:\Polymarket-Kelshi`. This skill is the human-confirmation step for REAL-MONEY orders.

1. `python -m src.pipeline pending` — list pending live orders. If none, say so and stop.
2. For each pending order, present: ticker, side, contracts, limit price, cost, net edge,
   consensus q vs market, and the one-line rationale from the ledger.
3. Use AskUserQuestion (multiSelect if several orders): execute all / pick subset / cancel all.
   NEVER execute without an explicit answer in this skill.
4. Execute chosen: `python -m src.pipeline execute-live --confirmed` (or `--id N` per order).
   Cancel rejected: `python -m src.pipeline cancel-pending --id N --reason "<user reason>"`.
5. Report placement results (order ids / failures). Then `python -m src.pipeline report`,
   commit and push.

Safety notes:
- If `live-check` has never passed in this environment, run it first and stop on auth errors.
- If the market moved so the limit price is stale (ask now worse than limit by >2c),
  point it out before asking - the order may not fill or may need re-pricing via a fresh decide.
