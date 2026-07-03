# Kalshi 集成研究 + 交易流水线

**四模型盲估 + 仲裁**的预测市场交易系统:2×Opus 4.8 与 2×Codex (xhigh) 独立盲估,
Fable 5 仲裁,决策引擎按净优势和硬风控下单——纸面与真钱双模式,全程审计入 GitHub。

```
scan → intel (agent-reach/web-access) → 盲估×4 (2 Opus + 2 Codex) → 仲裁/第二轮对辩
  → 验证层 (社媒+数据库) → engine (净优势≥5% 且 家族分歧≤10% 且 硬风控放行)
  → paper 账本 / live 挂单确认 → settle → report → git push
```

## 控制面 (对 Claude Code 说这些话就行)

| 你说 | 发生什么 |
|---|---|
| "跑一轮" / `/trade-cycle` | 完整循环: 扫描→研究→对辩→验证→决策→结算→日报→推 GitHub |
| "开扫" / `/scan-now` | 立即扫市场出候选表,问你要不要深挖哪几个 |
| "确认交易" / `/confirm-trades` | 列出待确认真钱挂单,逐单问你执行/取消 |
| (定时任务 kalshi-daily-cycle) | 每天 09:00 自动跑一轮 (桌面端开着时) |

交互会话中系统会在关键节点用**选择题**确认你的意志(选哪些市场研究、是否执行交易);
定时任务不打扰你,只在下单/分歧/风控/失败五种情况推送。

## 手动命令

```bash
python -m src.pipeline scan            # 扫描出候选清单
python -m src.pipeline rules TICKER    # 看单个市场结算规则
python -m src.pipeline decide --research reports/research_<date>.json
python -m src.pipeline settle          # 结算到期仓位
python -m src.pipeline report          # 日报 (含校准/开闸指标)
python -m src.pipeline status          # 账本摘要
python -m src.pipeline pending         # 待确认真钱挂单
python -m src.pipeline execute-live --confirmed [--id N]   # 执行真钱挂单
python -m src.pipeline cancel-pending [--id N]             # 取消挂单
python -m src.pipeline live-check      # 验证真钱 API 配置
```

## 模型编制与换代 (config.yaml `ensemble:`)

- **仲裁者/主AI**: 有 Fable 额度用 **Fable 5**,用尽切 **Opus 4.8**(交互会话用 /model 切换;
  定时任务跟随桌面端默认模型)。
- **估计者**: `claude_family.model`(Agent tool: opus/sonnet/fable...)与
  `codex_family.model`(codex -m: gpt-5.5...)。
- **未来升级到 Opus 5.0 / Codex 5.6 / 新 Fable:只改 config.yaml 两行,代码协议全不动。**

## 真钱交易配置 (三重开关,缺一不可)

1. **API key**: kalshi.com → Account → API Keys → Create,下载 RSA 私钥 `.pem`,然后:
   ```powershell
   setx KALSHI_API_KEY_ID "<key-id>"
   setx KALSHI_PRIVATE_KEY_PATH "D:\keys\kalshi.pem"   # 别放进仓库!
   ```
   重开终端后 `python -m src.pipeline live-check` 验证(显示余额即通)。
2. **config.yaml**: `mode: live` + `live.enabled: true`(这两个开关只能你自己改)。
3. **确认协议**: `live.require_confirm: true`(默认)= 每单经你确认(交互=选择题,
   定时=推送后等你 /confirm-trades);改 `false` = 全自动下单,硬限额仍然生效。

硬风控对 live 同样强制:单笔≤$25(取 risk 与 live 较小值)、日风险≤$100、
总敞口≤$300、日亏$150 熔断。`live_gate`(30 笔结算+Brier 优于市场+纸面盈利)
现为**建议性指标**,未达标时报告会标黄——开真钱前请自己看一眼。

## 目录

```
config.yaml            全局配置 (模型编制/交互/验证/风控/live 开关)
src/                   kalshi_client / scanner / engine / ledger / live / pipeline
research/PROTOCOL.md   研究纪律 (盲估、集成模式、验证层、铁律)
.claude/skills/        trade-cycle / scan-now / confirm-trades
data/                  candidates.json + ledger.db (审计账本, 入 git)
reports/               research_*.json + report_*.md (审计底稿, 入 git)
```

## 风险声明

预测市场扣费后是负和游戏。本系统第一目标是**用校准数据(Brier 分数)证实或证伪模型优势**;
真钱模式下的一切亏损由账户所有人承担。API 私钥永远不要提交进仓库。
