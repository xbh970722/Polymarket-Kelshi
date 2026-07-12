# 夜间复盘 2026-07-11

## 今日数字

- 已实现盈亏合计: **$+1.39** | 实时余额 $48.44 | live 敞口 $6.37
- 今日成交 4 笔 | 今日结算 4 笔 | 另有 2 笔 shortcycle 挂单未成交(VOID: 交叉价处 edge 不足, 见下)
- 分通道已实现:
  - shortcycle: **$+0.07** (Brier 0.0259 vs 市场 0.0347, n=35 — 模型优于市场, 但样本窄)
  - favorites: $+0.00 (吃价通道, q≡价格非模型)
  - weather: **$+1.32** (Brier 0.3247 vs 市场 0.31, n=24 — 模型劣于市场; 与今日 codex 修正后的口径不一致, 见"校准趋势")
  - ensemble: $+0.00 (尚无结算样本)
  - h10: $+0.00 (吃价通道) | h15: $+0.00 (吃价通道)
- **非交易层面的重大变化(非本次复盘任务所做, 系当天更早会话的自主降险动作, 此处仅记录)**:
  - shortcycle 已被 8 席委员会 (Fable×2+Opus4.8×2+codex5.6sol×2+Sonnet5×2) 判定"结构性负EV"并布尔关闭 (`enabled: true→false`, FREEZE-14 允许的②类动作, 无需用户批准, 纯降险)。日志显示今日 16:41 起持续输出 `shortcycle: shortcycle disabled`。
  - CORE/digest 政治时事直赌盘延续 07-11 五人会裁定的暂停 (见 CLAUDE.md #10), 在场仓位按既有规则跑, MEDNOM (q0.19 vs 市0.52, 32pt 分歧) 仍是监控活口。
  - crypto review #13 (21:25 提交): h15maker 重复复盘触发, 裁决 HOLD, 未改任何 config 数值 (FREEZE-14 合规)。

## 逐笔复盘

| 市场 | 方向 | 模型q | 市场价 | 结果 | PnL | 技能 vs 运气判断 |
|---|---|---|---|---|---|---|
| KXHIGHCHI-26JUL10-B81.5 | no ×1 @64c | 0.62 | 0.615 | settled yes | $-0.66 | **运气** — 模型与市场几乎重合(0.62 vs 0.615), 这是一笔"正常方差"下的败局, 62%信心的NO有~38%概率输, 不代表模型误判, 也谈不上市场教育了模型。 |
| KXHIGHNY-26JUL10-B87.5 | no ×1 @66c | 0.66 | 0.66 | settled no | $+0.32 | **中性/符合预期** — q与市场完全重合, 赢了但没有超额信息优势, 是"贴市场"型交易的正常结果, 不是技能证据。 |
| KXHIGHPHIL-26JUL10-B86.5 | yes ×2 @16c | 0.3721 | 0.155 | settled yes | $+1.66 | **需谨慎, 更像运气** — 这是直接 NWS 温度模型 (W1, 非fade), edge_net达0.2021, 表面看是"模型吊打市场"的大赢单。但今日 codex 独立复核已发现 W1(NWS-temp直报) 家族层面 n=11 胜率45.5%, Brier 0.2637 劣于市场0.2035, "无边际优势"; 这笔赢单更可能是稀薄样本(n=11)里的运气而非可复制技能, 不应据此扩大W1仓位。 |
| KXBTCD-26JUL1103-T63999.99 | yes ×1 @93c | 0.9811 | 0.925 | settled yes | $+0.07 | **符合家族画像, 非个例证据** — shortcycle terminal model 高信心小仓位, 单笔小赢符合"高胜率薄edge"画像; 但家族层面(n=406) 池化仍是 -$0.062/trade 显著为负 (8席会已裁定结构性负EV并关闭), 这一笔胜利不改变家族结论。另有同批2笔 shortcycle 挂单 (63999.99/64099.99 strike, 00:05) 因"交叉价处edge不足"未成交(VOID), 说明挂单逻辑本身在收窄edge时会正确拒单, 不是滑点/bug。 |

## 校准趋势

- **shortcycle**: Brier 0.0259 vs 市场 0.0347 (n=35) — 模型仍优于市场, 但通道已被关闭, 此曲线接下来不会再有新样本累积。
- **weather**: journal 口径 Brier 0.3247 vs 市场 0.31 (n=24, 模型劣于市场) — **与今日 codex 的 side-aware 修正结果不一致**: codex 发现 `weather_calibration.py` 存在 NO 侧 q_consensus 未按 YES 口径翻转 + 包含作废行的 bug, 修复后 (n=27) 模型 0.2344 vs 市场 0.2228, 拆分后 W1(NWS直报) 无边际优势, W2(fade) 反而以 0.1825 < 0.1860 **跑赢市场**。journal.py 用的很可能是未修复的旧口径 (n=24 而非27, 数值明显更差), **需要核实 journal.py 里天气 Brier 的计算路径是否也需要同一处 NO 侧翻转修复** — 这是代码口径一致性问题, 不是阈值/门槛调整, 建议下个会话核实并修正(非FREEZE-14管辖范围内的参数变更)。
- **market_calibration (mktcal, 全市场 7085 样本 tau≤20m)**: 各概率桶偏差普遍很小 (|bias| ≤ 0.048), 0.2-0.3 桶 (+0.043) 和 0.4-0.5 桶 (+0.048) 略微偏高但样本量分别只有509/498, 未见系统性方向性偏差。favorite-side (0.75-1.00) 偏差 -0.012~+0.022, 同样无明显系统性偏誉/偏贬, 与此前"favorite-bucket bias"担忧相比, 当前快照看不出恶化趋势。
- **H9 (午夜重开滞后富集假说)**: 今日**无法检验** — shortcycle 已整体关闭(该假说原本挂靠在滞后通道上), h10 shadow gate 状态为 KILL(0 pending), 日志中未见任何按小时切片的滞后通道通过率分布数据被专门统计。此假说目前处于停滞状态, 待 07-23 判决时一并处理是否归档。

## 回归测试

- `tests/test_ledger_live.py`: **PASS** (`ALL LEDGER LIVE-STATE TESTS PASSED`)
- `tests/test_swing.py`: **PASS** (`ALL SWING TESTS PASSED  take-profit pnl=$+1.95, Brier n_settled=0, swing_pnl=$+1.95`)
- 今日提交未触及 `src/` 下任何订单路径文件 (`git log --since 2026-07-11 --name-only` 无 `src/*` 改动, 只有 `data/`, `research/SHORTCYCLE_DESIGN.md`, 报告类文件), 因此**无需**额外手动重跑 `tests/test_failures.py`。

## 明日提案

以下均为**提案**, 不自动执行 (交易门/尺寸/zone/z_floor/止损参数变更受 FREEZE-14 冻结至 07-23; 代码口径修复类不受此限但仍留给用户/下一会话核实):

1. **[代码口径] journal.py 天气 Brier 计算** — 现状: journal 口径 n=24, Brier 0.3247 vs 市场 0.31 (模型劣于市场); codex 今日修复 weather_calibration.py 后口径 n=27, Brier 0.2344 vs 市场 0.2228 (差距缩小, 且拆分后 W2 跑赢市场)。提议: 核实 journal.py 是否复用了同一个未修复的计算函数, 若是则同步修复, 让每日复盘的天气 Brier 数字可信。
2. **[待07-23裁决, 仅记录不改]** maker-exit-leak 提案(favorites/h15 全部单边maker通道): held-to-settlement 若本可全赢($28.70 @97%胜率), 早退出反亏$43.48, 需先查证"held-to-settlement 是否本会赢"再谈是否重启 favorites。
3. **[待07-23裁决, 仅记录不改]** tau-conditioned 止损设计: 主Fable提议"临近收盘关闭止损/止盈, 只在窗口前段生效", codex 已提出反对意见(近strike+近收盘的高gamma情形可能仍需要止损, 且"退出价≈公允价"已能解释现有wash现象, 无需tau理论), 需要修订后再进入回测。
4. **h15maker 隔离观察** — 累计已实现 -$4.56, per-position -3 硬止损已生效, 继续保持隔离以保留07-23判决所需的预注册样本, 不关闭不收紧。
5. **W1(NWS直报) vs W2(fade)** — 今日codex修正后的证据支持"W1无edge, W2有潜在edge但样本太薄(n=10)不能放大"的框架; 建议后续复盘按W1/W2拆开统计, 不要再合并成单一"weather"口径, 以免像今日这样掩盖内部结构。

以上均已存在于 `data/change_proposals.jsonl` (今日多条, 分别来自 supervisor-maker-taker-audit / Fable-lead-8seat-council / codex5.6sol-xhigh-verify 等), 本复盘仅做归纳呈现, 未新增提案队列条目。
