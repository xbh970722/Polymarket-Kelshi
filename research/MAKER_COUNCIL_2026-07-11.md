# 8人策略会: maker 早平仓/逆选择裁决 (2026-07-11)

Fable 主持。用户命题"早平仓该怎么办"。Fable 先拉证据, **推翻前提**: 早平仓不是主漏。

## 编制与各席一句话裁决
| 席位 | 模型 | 裁决 |
|---|---|---|
| 主持/综合 | Fable-5 (lead) | 早平仓近乎平手; 漏在入场; 初判"保子集"被 Fable-2 证伪 |
| 共同架构师 | Fable-5 | **STANCE=A high**: pooled t=−2.02 才是真信号, 子集无统计力; 关 shortcycle, 记提案 |
| 机制/内视 | Opus-4.8 | structural-short-vol; 大漏(favorites/h15/h10)已封, **仅 shortcycle 仍 live (signal-miss)** |
| 基率/外视 | Opus-4.8 | **STRUCTURAL_EV=negative, KEEP_SUBSET=no**; 单边无对冲=裸卖尾部保险; 有 Stanford/Bartlett 4160万笔实证 |
| 实现 | Sonnet-5 | shortcycle 无侧级键(side 算法定); 关/降=纯config; 侧筛/白名单=需代码+提案 |
| 合规 | Sonnet-5 | **AUTONOMOUS=[降尺寸,布尔关,记提案] PROPOSAL=[关某侧,白名单] USER=[重开favorites]** |
| 红队/攻方 | codex-5.6-sol | STANCE=C 但 kill_switch_now=[shortcycle,h15 布尔关]; 8格 bootstrap CI 全跨0=过拟合 |
| 定量/核验 | codex-5.6-sol | 我的表 0/8 零出入; **无任何价 band +EV** (胜率<盈亏平衡); n_sufficient=false |

## 决定性证据
1. **早平仓非主漏**: 66 笔 closed maker 全查结算, 持有到底 −$46.93 vs 割肉 −$53.57, 差 +$6.64, 34/32 近五五开 → 止损尽责。
2. **结构性负 EV** (最硬): 每个入场价 band 的实际胜率都 < 该价隐含盈亏平衡胜率 (L 10%<33%, M 73%<85%, H 87%<92%)。pooled 406 笔 −$0.062/笔 t=−2.02, 8天7负。
3. **"+EV 子集"是过拟合**: 8 格 bootstrap 95% CI 全跨 0, n_sufficient=false; ETH-yes/XRP-no 是本周 up-drift 体制 + 下注尺寸运气, 非 edge。
4. **机制**: favorites/h15/h10=结构性 short-vol(恒买热门=卖尾部险, 负偏度); shortcycle=零漂移模型在趋势体制高估 NO=signal-miss。

## Fable 总裁决 (决定性处果断, 争议处谦抑)
- **关 shortcycle** (enabled→false): 全票, 最大 live −EV 敞口 (max 5), 仍在滴血 → **已自主执行** (FREEZE-14 ②类降险, CLAUDE.md"停通道永远可直接做")。
- **h15 不动**: 争议。会议分析的是**混合** ETH-yes(−0.043), 但 h15 config 记录**隔离**的 KXETH15M-YES=89%胜 +$6.48 对齐回测, size-1, 队列位置研究使命 → 记提案, 07-23 用隔离数据裁。
- **不做"保子集"**: 全席否 (多重比较过拟合)。侧筛/band/止损调参 = 只记提案。
- **复活判据** (07-23): 下行体制周 n≥100 且费后 pooled edge > +2c。重开=用户专属。
- **精力转向**: taker-weather (W1 +$1.89 / W2 +$1.28, 唯一干净正, 无早平仓放血)。

已停通道的 mktcal 校准采样继续免费跑, 停交易不丢研究数据。
