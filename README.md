# Kalshi 双模型研究 + 纸面交易流水线

信息/模型优势策略的全自动流水线:**Claude (Fable 5) 与 Codex (gpt-5.5 xhigh) 独立盲估 + 对辩**,
决策引擎按净优势和硬风控自动下单——当前阶段写入**纸面账本**,不碰真钱。

```
scan (Kalshi API)  →  intel (agent-reach/web-access)  →  盲估×2  →  对辩
      →  engine (净优势≥5% 且 分歧≤10% 且 风控放行)  →  paper ledger  →  settle  →  report
```

## 使用

在 Claude Code 里说 **"跑一轮"** 或 `/trade-cycle`,它会执行完整循环。手动命令:

```bash
python -m src.pipeline scan                                   # 扫描市场出候选清单
python -m src.pipeline rules KXFED-26JUL-T4.00               # 看单个市场结算规则
python -m src.pipeline decide --research reports/research_2026-07-03.json
python -m src.pipeline settle                                 # 结算已到期仓位
python -m src.pipeline report                                 # 生成日报 (含校准与开闸检查)
python -m src.pipeline status                                 # 账本一行摘要
```

## 关键设计

- **盲估防锚定**: 两个模型都先不看市场价独立估概率,再对辩更新 (research/PROTOCOL.md)。
- **引擎决策**: 共识概率 − 市场价 − 手续费 ≥ 5 个概率点才下单;1/4 Kelly 仓位;
  单笔≤$25、单日≤$100、总敞口≤$300、日亏$150 熔断 (config.yaml)。
- **校准闭环**: 每笔交易记录模型概率与市场概率,结算后算 Brier 分数——
  直接回答"模型到底比市场准不准"。
- **开闸条件** (三条全过才讨论真钱): ≥30 笔结算 + Brier(模型)<Brier(市场) + 纸面盈亏为正。
  在此之前 `mode: live` 会被代码硬拒绝。

## 目录

```
config.yaml            全局配置 (领域/阈值/风控/开闸条件)
src/                   kalshi_client / scanner / engine / ledger / pipeline
research/PROTOCOL.md   研究纪律 (盲估、对辩、铁律)
.claude/skills/        trade-cycle skill (完整循环的执行手册)
data/                  candidates.json + ledger.db (纸面账本)
reports/               research_*.json + report_*.md
```

## 风险声明

预测市场扣费后是负和游戏。这套系统的第一目标是**用纸面数据证伪或证实模型优势**,
不是保证盈利。真钱阶段的一切亏损风险由账户所有人承担。
