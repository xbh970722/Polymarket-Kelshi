---
name: scan-now
description: Instant Kalshi market scan without the full research cycle. Use when the user says "开扫", "扫一下", "scan", "看看现在有什么市场", or wants a quick shortlist of liquid markets right now.
---

# Scan Now

Work in `D:\Polymarket-Kelshi`.

1. Run `python -m src.pipeline scan` and show the shortlist as a readable table
   (ticker, category, mid price, 24h volume, days to close, title).
2. If the session is interactive AND `interaction.when_interactive: ask` in config.yaml,
   use AskUserQuestion (multiSelect) to ask which candidates the user wants:
   - 深度研究这几个 (invoke the trade-cycle research flow on the picks)
   - 只存档不研究
   - 调整过滤器 (then edit the `scanner:` section per their wishes and re-scan)
3. If the user picked markets to research, hand off to the trade-cycle skill flow
   (research those specific tickers instead of auto-picking).
4. Commit and push if anything changed: `git add -A && git commit && git push`.
