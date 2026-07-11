# 复盘 2026-07-10

## 今日数字

- 已实现总计 **$+0.30** | 余额 $45.83 | live 敞口 $7.25
- 今日成交 19 笔 | 结算 18 笔 | 仍 open 4 笔 (KXHIGHCHI-0710, KXHIGHNY-0710, KXHIGHPHIL-0710, KXBTCD-1100)
- 分通道: **shortcycle $-0.96** | **weather $+1.26** | favorites/ensemble/h10/h15 均 $0.00 (吃价通道或无结算样本)

## 逐笔复盘

**weather 通道 (W2 fade + NWS 模型): 3/3 结算全胜**
- KXHIGHPHIL-0709 no@62c、KXHIGHMIA-0709 no@69c: W2 fade 策略, yes 报价落在 [.15,.40] 区间 (66天回测 99.5% 置信带), 两笔均小胜 (+0.36 / +0.30)。
- KXHIGHNY-0709 no@38c: NWS 数值预报 (mu 84.0F, obs_max 79.0, fc_max 84.0) 直接量化了市场定价偏差 (市场隐含 62% yes, 模型给 37.2%), edge_net 高达 0.22, 结算 no 兑现 +0.60。这是**可归因技能**——预报数字本身就是可验证的偏差来源，不是运气。

**shortcycle 加密通道: 13 笔中 7 笔被 stopguard 提前止损, 6 笔跑到结算**
- 结算的 6 笔全部方向正确 (XRP/ETH/BTC, q 多在 <0.1 或 >0.9 高置信区间), 单笔 $0.07~$0.29, 印证了不错的方向读数。
- 但 7 笔止损 (KXBTCD×6 + KXSOLD×1) 合计吃掉 -$2.04, 抹掉了结算端的胜利, 净拖累通道到 -$0.96。最大单笔亏损 KXBTCD-1005 (-$0.61): 入场时模型给 no 91.6% 信心 (q=0.084), 价格从 87c 一路跌到 stopguard@28c 才平仓——说明短期内 spot 一度显著逼近 strike, 属于短线终端模型低估近撞线波动的场景。
- **技能 vs 运气判断**: 止损单不能简单记为"模型判断错误"——止损可能正是风控在正确地防止更大亏损。但也不能简单记为"纯运气不好"——7/13 的止损触发率偏高, 值得后续拆解止损前 unrealized 峰值亏损, 才能判断是尾部波动的正常代价, 还是 stopguard 阈值系统性偏紧。今天的数据不足以下结论 (见明日提案)。

**gate 活动**: disloc 通道全天 242 次 "accumulating/KILL/ARCHIVE" 决策 (n=28 pending, 尚未开闸); pmwatch 12923 行、3946 条与 Kalshi 匹配, divergence 中位数 4.5c (gate 需 n>=300 才评估)。日志中未见 NOFILL 专项埋点，无法单独统计报价空跑比例。

## 校准趋势

- **市场整体校准** (6258 样本, tau<=20m): 多数桶偏差在 ±1.2pt 内, 属正常范围; 0.2-0.3 (+0.030) 与 0.4-0.5 (+0.033) 两个桶市场略低估, 0.80-0.85 favorite 桶市场略高估 (-0.018)。
- **shortcycle Brier 0.0275 vs 市场 0.0359** (n=32) — 模型优于市场, 方向读数扎实。
- **weather Brier 0.3247 vs 市场 0.2928** (n=21) — **模型实际上略逊于市场**, 但通道今天照样盈利 $1.26。这说明今天的盈利主要来自少数几笔高 edge 单 (尤其 KXHIGHNY), 而不是整体概率读数系统性优于市场; n=21 样本太小, 现在下"weather 通道跑赢市场"的结论为时过早, 有拟合到单日天气模式的风险。
- **H9 (时区断层/午夜重开滞后假说)**: 已于 2026-07-05 按日历到期规则**归档否决** (单观察、无经费、无累积路径, 无新证据自动归档)。今日日志中 `lag_only` 通道出现 **0 次**, 与归档状态一致——不需要重新评估, 也没有新证据支持复活。

## 回归测试

- `tests/test_ledger_live.py`: **PASS** (ALL LEDGER LIVE-STATE TESTS PASSED)
- `tests/test_swing.py`: **PASS** (take-profit pnl=$+1.95, swing_pnl=$+1.95)
- 今日 src/ 有 2 次提交 (3e3b256 events 研究编排器, 9dffe64 三条新 paper-only 研究通道), 均触达 `src/pipeline.py`，但只新增 `events-*` 子命令 (dormant, paper-only), commit message 声明已 grep 校验 zero live-order paths, 未改动既有下单/结算路径 —— `tests/test_failures.py` 无需手动重跑。
- 另注: 日志显示 20:46-20:48 曾两次 `git push` 因 DNS 解析失败被拒 (`Could not resolve host: github.com`), 但 21:36 最终 commit+push 成功, 判断为瞬时网络抖动, 无数据丢失。

## 明日提案

1. **shortcycle stopguard 阈值诊断** (当前: 触发即按市价平仓, 无峰值回撤记录) → **提案**: 加一个日志字段记录止损单触发前的 unrealized 峰值亏损, 与最终 stopguard 实现亏损对比。若峰值远超止损点位, 说明阈值合理保护了尾部风险；若峰值只是略超触发点随即反弹, 说明阈值可能偏紧、带来不必要 bleed。数据积累到 n>=20 笔止损单后再判断是否需要调整——**冻结期内 (FREEZE-14, 至 07-23) 任何数值收紧/放松都只能进 `change_proposals.jsonl` 队列, 不直接改 config**。
2. **weather 通道样本量** (当前: n=21, Brier 略逊市场) → **提案**: 暂不因今天 +$1.26 的盈利就上调 weather 通道预算/尺寸, 继续观察到 n>=50 结算样本再评估 W2 fade + NWS 模型是否系统性跑赢市场, 避免单日天气模式过拟合。
3. **H9 文档存档确认** (当前: SHORTCYCLE_DESIGN.md 记录 07-05 归档) → **提案**: 下次周报 (07-12 周日) 若仍无新证据, 可在文档追加一行"07-10 复核: lag_only 通道 0 次触发, 维持归档"作为存档确认——这是研究文档记录, 非 config.yaml 交易参数, 不受 FREEZE-14 管控, 但仍等下次周报统一处理, 不在本次复盘中直接改文档。
