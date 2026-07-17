# 交易反思 2026-07-16（周四）· 收盘版

> 自动夜间反思 · 仅分析，不交易、不改 config。FREEZE-14 生效中（至 07-23），一切参数变更只记提案。
> （本文覆盖今晨机器恢复后的 stub：交易日已恢复，全天真实成交 4 笔、结算 1 笔。）

## 今日数字

- **实时余额 $42.58** ｜ live 敞口 $1.49 ｜ **今日已实现 −$0.57**
- 今日成交 **4 笔**（3 天气 + 1 PCE）｜今日结算 **1 笔**（PCE 止损）
- 分通道已实现：
  - shortcycle **$+0.00**（Brier 0.0259 vs 市场 0.0347，n=35）
  - favorites **$+0.00**（吃价通道，q≡价格）
  - weather **$+0.00**（Brier 0.3103 vs 市场 0.3268，n=30；今日 3 笔未结算）
  - ensemble **$−0.57**（PCE 止损，尚无累计 Brier 样本）
  - h10 / h15 **$+0.00**（吃价通道）
- risk used $2.06；开仓 4/16；敞口 $1.49/$300。日亏 −$0.57 距 −$200 熔断极远。

**⚠️ 余额口径异常（需用户核对，非交易亏损）**：余额从今晨恢复时的 $57.52（04:14 上电快照，且 07-13 行同为 $57.52）跌到 21:22 的 $42.58，**同日内 −$14.94**。但账本今日仅记 **−$0.57** 已实现 + 约 $1.4 新占用敞口，两项合计 ~$2，**剩余 ~$13 无法从账本归因到任何交易**。佐证：① 21:22 `cash_check.json` reconcile `cash drift $0.00`（账本现金模型与交易所对得上，无隐性泄漏）；② 全窗口 closed 行仅 6 笔净 −$1.49，且 0 笔未入账 swing；③ 余额列本身含 MTM/挂单预留噪声（07-12→13 曾在 −$0.92 亏损日反涨 +$4）。**这不是隐藏交易亏损**——与"同日 −$0.57 记录 + drift $0.00"最一致的解释是 **07-16 发生了一次用户现金提取（充/提是用户专属杠杆，AI 不代行）**，或余额快照语义变化。**请用户确认交易所是否有 07-16 的提现/划转**；账本侧无需动作。

## 逐笔复盘

**唯一结算：KXPCECORE-26JUN-T0.2 · yes ×13 @ 5c → 止损 @1c · pnl −$0.57**（模型 q=0.1075，市场 0.03，ensemble）

- **技巧 vs 运气拆分**：5c 长尾单（隐含 3–11%），单张 ~10% 的注按期望 ~90% 时间会输——**单次亏损不构成"下错"的证据**（结果论陷阱）；止损 @1c 把损失锁在 −$0.57，纪律良好。
- **但过程层有真实红旗（非运气事件）**：这是"core PCE **above 0.2%**"门槛盘。按单小数进位陷阱 [[kalshi-pce-cpi-single-decimal-rounding]]，结算 YES 需上报值 ≥0.3%（真值 MoM **≥0.25%**）。而本单 rationale 自引的 Cleveland Fed nowcast = **0.19% MoM**，**远低于** 0.25% 进位边界——YES 公允概率大概率**比市场 0.03 还低**，4 盲估计者却聚在 0.10–0.13，**系统性高估 YES**：定价没吃进进位门槛。**这一单市场比模型更校准**。
- **机制关联**：ensemble 宏观打印盘用"4 盲估计者"定价，结构同 moratorium 下的 digest/CORE 盲估 [[core-llm-direct-betting-moratorium]]——"盲估信息集 ⊆ 市场"、越偏离越重仓的负 EV 型。虽属 ensemble 非政治 CORE lane，仍需盯：勿复现同一陷阱。

**未结算（暂无技巧/运气裁决）**：天气 3 笔 KXHIGHNY-T89 no@46c(q0.04)、KXHIGHPHIL-B96.5 yes@20c(q0.37)、KXHIGHMIA-B94.5 yes@45c(q0.77)（EOD 按 NWS mu/sigma 结算）+ Alito #62 yes@11c(q0.17，旧仓 hold 到 08-01)。报告里这些仓 mark 0.01 是 15m light-mark 保守最差价，unreal −$1.44 为名义值。

## 校准趋势

- **累计已结算校准（favorites 按设计排除）**：49 笔结算，胜率 55%，realized **+$6.45**，**Brier(模型) 0.0984 < Brier(市场) 0.1167 → 模型仍占优**。分通道同向：shortcycle 0.0259<0.0347、weather 0.3103<0.3268（天气 Brier 绝对值高≈0.31，难预测域，含金量有限）。
- **市场 favorite 桶偏差（mktcal，9555 样本，tau≤20m）**：多数桶小幅正偏——0.85-0.90 **+2.3%**（热门实际 0.898>定价 0.875）、0.90-0.95 +0.3%、0.95-1.00 +0.7%；最大偏差在中价 **0.40-0.50 +4.2%**（n=656）与 0.20-0.30 +1.9%。持续轻微 favorite richness，与历史一致，无新拐点。
- **H9（午夜重开 lag 富集）今日无法评估——数据不足**：今日 quant_loop.log 该段只有 `report: wrote` 与每小时 `manage: done`（holding 1→3→4，17:41 出 1），**无任何 lag-gate 通过/拒绝记录**；今日 0 笔经 loop 入场路径的 lag-gated 进场（3 天气 + 1 PCE 走独立 light-mark/入场进程，且天气/ensemble 本就不吃午夜重开 lag 门）。小时级 lag-gate 通过分布**今日零新样本**，H9 无信号。如实记录，不外推。
- **影子门现状（承晨间 stub，累计口径，无一可晋升）**：h10 **KILL**（n=941 均 −1.3c/张 已确认死）；H13 final6 **accumulating**（n=121 胜 120/121 净 +$2.07，但 clean n=46 样本不足）；disloc **accumulating**（BOOK-ONLY 子集 n=267 EV +2.5c 是唯一亮点）；wxfade **ARCHIVE（edge dead）**（n=210 均 −5.4c/张）[[wxfade-w2-archived-tau-exit-spec]]。高胜率+小 clean-n 是最典型过拟合陷阱，勿因 H13 的 120/121 心动。

## 回归测试

- `tests/test_ledger_live.py` → **PASS**（ALL LEDGER LIVE-STATE TESTS PASSED）
- `tests/test_swing.py` → **PASS**（take-profit pnl=+$1.95，swing_pnl=+$1.95，Brier n_settled=0）
- 两者确认为合成测试（scratchpad 一次性 DB，无 `KalshiLive`/无网络/无下单，grep 零 live 调用），符合任务"synthetic, no money"，未违反 CLAUDE.md#5 实弹纪律。
- **test_failures.py 无需手动重跑**：今日全部提交只动 `data/`（日志、shadow db、json/cash_check），**未触碰 `src/` 任何下单路径代码**。

## 明日提案（仅记录，绝不自行应用；FREEZE-14 下门/尺寸/阈值变更一律入队 07-23）

1. **[交易参数 → 仅入队]** PCE/CPI 进位门槛硬护栏：下单"above X%"通胀门槛盘前，定价须先套单小数进位（"above 0.2%"仅当 rounded ≥0.3%/真值 ≥0.25% 才给 YES 正概率）。`当前`=盲估给 q≈0.11 而 nowcast 0.19% 低于 0.25% 进位边界 → 结构性高估；`建议`=nowcast<(门槛+0.05) 时对 YES 的 q 设上限/触发 veto；`依据`=今日 −$0.57 + [[kalshi-pce-cpi-single-decimal-rounding]]。数值收紧=冻结期提案，07-23 裁。
2. **[验证层 → 仅记录]** ensemble 宏观打印盘纳入盲估 veto 范围：本单机制同 [[core-llm-direct-betting-moratorium]]。`建议`=把"大 |q−市场| + 仅盲估 → 跳过"的否决权从 CORE/digest 扩到 ensemble 宏观打印，或要求独立硬数据锚（进位边界）作 veto，而非仅靠 family divergence 门。
3. **[基础设施 → 可提可做，非交易门]** 整机停摆自愈：07-13(14.4h)+07-14→16(43.5h) 两次空档，后者 watchdog.log 零条目=整机关机/休眠而非进程崩溃 [[quant-loop-14h-outage-2026-07-13]]。`当前`=watchdog 仅机器开机时能拉起；`建议`=核 Windows 电源/睡眠与唤醒计时器设置，评估禁休眠或加自动唤醒；并核实恢复消息里 "was down/**hung**" 是否表示日志新鲜度检查已入代码。
4. **[数据连续性 → 可提可做]** 停摆日 07-15 在 pnl_history.csv 整行缺失、07-14 余额字段空。`建议`=journal/settle 增"补写零行"逻辑，缺失日回补一条承前余额的零损益行，避免日期跳空污染按序列的校准/回撤统计。
5. **[ops → 仅记录]** 余额口径透明化：pnl_history 余额列混入 MTM/挂单预留（−$0.92 日却 +$4；今日 −$0.57 记录却掉 $14.94）。`建议`=在噪声 live-balance 快照旁并记干净的 `settled_cash` 列，便于每日反思干净归因现金漂移。
6. **[交易参数 → 仅入队，背书 supervisor/Fable 今日已入 `data/change_proposals.jsonl` 的三项]** h15maker reflag-suppression（Review #18，治 review-churn）、tau-exit「VOID-for-insufficiency」并作 maker 复活基建停放（n=4≪预注册 n≈100）、tick 保留 ≥30 天。均 07-23 一并裁，本次无动作。

---
*诚实声明：今日真实亏损仅 −$0.57（PCE 长尾止损，市场比模型更对），非"平静的一天"——余额同日掉 $14.94 待用户确认现金进出；账本、reconcile、回归测试三方一致，无隐藏交易损失。今日为周四，非周报日；−$0.57 > −$5 告警阈值，不推送。*
