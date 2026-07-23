# 交易复盘 2026-07-23 (周四)

> 分析报告，不下单、不改 config。今日恰逢 FREEZE-14 边界日，但裁决属独立 Fable 会话 (research/FREEZE14_ADJUDICATION.md)，本复盘只记录、不裁决、不动任何门。

## 今日数字

- **今日已实现 P&L: $0.00** — 0 成交、0 结算。安静日。
- 分通道今日已实现: shortcycle $0.00 / favorites $0.00 / weather $0.00 / ensemble $0.00 / h10 $0.00 / h15 $0.00。
- 实时余额 **$41.40** (reconcile: 对账现金 OK，drift $0.00，reserved $0.00)。
- live 敞口 **$0.12** — 唯一持仓仍是那笔"史上第一单"验证仓 KXALITOANNOUNCERETIRE YES ×1 @$0.11 (2026-07-04 开，从未平；exit_type=hold)。
- **⚠️ 运维事故 (比数字重要)**: quant_loop 日志从 **07-19 18:38 断到 07-23 00:47 (~78 小时 / 3.25 天空档)**。07-20/21/22 三天无循环、无反思 (pnl_history 亦从 07-19 直接跳到 07-23)。这是继 07-13 (14.4h) 与 07-14→16 (43.5h) 之后的**第三次多日停摆**，且是三次里最长的一次。今晨由 supervisor 拉起 (新 pid 26732)。07-19 断线前日志满是 `NameResolutionError` (DNS 解析 api.elections.kalshi.com / github.com 失败) → 整机网络掉线是直接诱因，与 07-14 的整机下线同型。
- **h15 硬停火**: 日志 `h15 HARD STOP: realized $-4.56 — paused pending review`。h15 吃价通道累计已实现触及硬止损阈，**自锁暂停**。这是 FREEZE-14 允许的第①类硬安全刹车 (按现有规则开火)，非改门。

## 逐笔复盘

今日 0 笔成交、0 笔结算 — 无个案可复盘。以下是**在场/近端**值得记录的两点，均为机制而非今日行为:

- **h15 累计 −$4.56 → 硬停**: 记忆档 [[maker-harvest-structural-negative-ev]] 记录 h15 "待 7-23 隔离裁"。它没等到人工裁决，自己先在边界日 (07-23) 撞上硬止损自锁。这不是"运气不好"——它是**预注册就判为结构性负 EV** 的通道 (每 band 胜率 < 盈亏平衡)，−$4.56 的累计亏损是对该预期的**兑现，不是意外**。技能 vs 运气判定: 这是"事前正确判死、事后如期亏损"，属于**风控系统按剧本正确执行**，值得记一分给纪律，不是新失败。
- **那笔 Alito 验证仓 (敞口 $0.12)**: 持有 19 天未动，YES @$0.11。它是买入路径的验证单、金额可忽略。reconcile 连续告警 `BOOKED_TS NULL #62` (账本行缺现金落地时间戳) — 监工已定性为 **chronic benign，非现金错配** (现金对账仍 OK)。不是错误，是一条陈年脏数据。

## 校准趋势

- **模型 vs 市场 Brier (favorites 按设计排除)**:
  - shortcycle: **Brier(模型) 0.0259 vs Brier(市场) 0.0347 (n=35)** — 模型领先 0.0088，仍在赢市场。样本小 (n=35)，但方向持续为正。
  - weather: **Brier(模型) 0.3231 vs Brier(市场) 0.2863 (n=36)** — 模型**落后市场 0.0368**。天气通道模型口径持续不敌市场；今晨该通道还因 `mtm snapshot stale >2h` 自我 VETO 拒绝新单 (对未实现盲即刹车，正确)。
- **市场校准 / favorite 桶偏差趋势** (mktcal, 10221 样本, τ≤20m): 各桶整体校准良好。favorite 侧偏差多为**小幅正值** (0.75-0.80 +0.026、0.85-0.90 +0.025、0.90-0.95 +0.004、0.95-1.00 +0.008)，仅 0.80-0.85 为 −0.011。即**热门侧略微被低估、赢率略高于挂牌价**——温和的 favorite richness 持续存在，未见反转。主盘 0.4-0.5 桶 +0.043 (implied 0.449 vs realized 0.492) 是最大单桶偏差，中价区轻微低估。
- **H9 (午夜重开滞后富集) 本周期不可观测**: shortcycle 与 favorites 两条会激活 lag-gate 的通道**当前都 disabled** (日志: "shortcycle disabled" / "favorites lane disabled")，小时级 lag-gate 无 pass 产出，故 H9 无法从今日 pass 分布中读出。要观测 H9 必须先有一条 lane 跑 lag-gate — 冻结期内不动。
- **旁证影子门 (仅记录，非本轮决策)**: h10 shadow gate=KILL (n=1151, total −$6.85, KXSOL15M −$4.42 最差)；wxfade gate=ARCHIVE 边缘已死 (n=269, mean −6.0c/张, total −$16.04)；disloc BOOK-ONLY 子集 EV +2.8c (n=362, win 86%) 仍是唯一亮点，accumulating 中；H13 final6 n=164 win 161/164 gate=ARCHIVE。

## 回归测试

- `python tests/test_ledger_live.py` → **PASS** (ALL LEDGER LIVE-STATE TESTS PASSED)。
- `python tests/test_swing.py` → **PASS** (take-profit pnl=$+1.95, swing_pnl=$+1.95, Brier n_settled=0)。
- **今日 commits 未触及下单路径**: 三次提交 (5deb5be3 / 720a8f99 / 12948e16) 只改 data/*.json、data/*.db、reports/*、quant_loop.log — 无 src/live.py / src/pipeline.py 下单函数 / src/swing.py 改动。故 **tests/test_failures.py 无需手动重跑**。

## 明日提案

> 均为提案，一律不改 config (VALUES.md 5f + FREEZE-14: 风险/门槛变更归用户，冻结期"推荐"=记提案)。已存在的可自主动作 (硬刹/布尔关/整数降尺寸/记提案) 不在此列。

1. **[运维·最高优先级] 修 quant_loop 多日停摆 (第三次)**。现状: 07-13 (14.4h)→07-14/16 (43.5h)→**07-19/23 (78h)** 三次停摆且间隔在缩短、时长在拉长；watchdog 未能在整机 DNS 掉线场景下自愈 (07-19 断线前日志是 NameResolutionError，watchdog 自身可能同时下线)。提案: (a) 给 watchdog 加**网络恢复探测 + 心跳落盘到仓库外稳定路径** (D:\kalshi-ticks\)，掉线期也记 tick，恢复后能判断空档；(b) 加一条**独立于主机的死信告警** (若 >6h 无 supervisor commit 则推送)，本次 78h 无人知晓直到今晨拉起。数据支撑: 三次空档共丢 ~135h 交易/采集覆盖。**此为纯运维/可靠性提案，不涉及交易门，可由用户批准后直接施工。**

2. **[运维] 修 git 自动推送凭据失效**。日志: `Unable to persist credentials with the 'wincredman' credential store` — 07-23 两次 push retry 均 FAILED，"committed + pushed" 是假象 (本地提交成功、远端未收到)。提案: 切 GCM 凭据存储或改用 PAT 环境变量。当前风险: 本地磁盘一旦坏，GitHub 上没有近三日的备份。**纯运维，不涉及交易参数。**

3. **[记提案·不即改] weather 通道模型口径落后市场 0.037 Brier (n=36)**。现状 z_floor/zone 冻结中。观测: 模型 Brier 0.3231 > 市场 0.2863，且非孤例 (前几日反思亦见)。提案进 change_proposals.jsonl: 冻结到期后评估**天气通道是否应从"模型定价"降级为"仅影子"**，直到模型 Brier 稳定跑赢市场。**数值收紧亦算改门 → 只记队列，07-23 边界裁决由 Fable 会话按预注册判据表处理，本复盘无权推导。**

4. **[记提案] h15 硬停后的处置**。h15 已自锁 (第①类刹车)。提案: 保持 paused，**不重启**，纳入 FREEZE14 裁决队列作为"预注册负 EV → 如期兑现"的样本 (−$4.56 累计)。重启/加钱=用户专属，不在自主范围。

---
*边界日说明: 07-23 是 FREEZE-14 边界日。本反思任务只做分析。交易门/尺寸/zone/z_floor/止损/体制参数的裁决属独立 Fable 会话按 research/FREEZE14_ADJUDICATION.md 三列判据表一次性处理。本复盘未改任何 config 数值，未裁决任何提案。*
