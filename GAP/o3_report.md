# GAP-245 · O3 席报告 — 总红队交叉互审 (采纳前最后一道关)

**席位**: O3 (Opus 4.8, 总红队) · **指挥**: Fable 5 · **日期**: 2026-07-05
**任务**: 交叉互审 c1-c6 + o1 + o2 九份报告 (b1 未出现, 跳过)。专找数字矛盾、口径混用、互相打架、伤钱的坑。
**铁律遵守**: 全程 DB 只读 (`file:...?mode=ro`); 未下任何单; 未碰 D:\kalshi-secrets; 未改任何现有仓库文件; 未 git; 未杀进程。所有数字用同目录复算脚本/CSV/JSON 或只读 DB (`data/ledger.db`, `data/stop_shadow.db`) 重验。

---

## 0. 一页结论 (给指挥)

- **最伤钱的坑**: O2 §2.3/§5 对 **#76 方向判反** —— 把一个真死单说成"裸止损割掉赢家、双条件救回 $1.62"。账本铁证 #76 是 **NO 持仓、结算 YES、归零、hold 亏 $2.46**;裸止损反而亏得更少(-$1.05)。O2 的核心反例站不住,"裸止损=提款机"论点当前**无真实赢家样本支撑**。→ **CONFIRMED,已挂修正任务。**
- **无实质矛盾但需并读**: C3 "tau 优势来自窗口位置" 与 O1 "净 edge 随 tau 升、挪扫描点" **不打架**,组合含义清晰: **可以挪扫描点到高 tau 吃肥窗口, 但别为"WS 早发现"花钱**(只值 0-1.2pt)。→ **BOTH-VALID(互补)。**
- **过严 vs 如实**: C5 的 MC 门 + C4 的跨体制门若**叠成单一 pre-Sept 门 = 过严**(全天候晋升到 2026-09-01 前**现实不可能**, storm 样本=0);但**分成两层则如实**: calm-only 门 h10 有望 9 月前过, 全天候门本就该是更晚的里程碑。→ **裁决: 分层,不叠加。**
- **基建**: 蓝图"事件驱动快照 + 死盘降频"对 O1 |z| 研究和 O2 驻留验证 **够用**,唯一红线是死盘降频的盲区,需"任一 delta 立即重开满速"护栏。→ **够用 + 1 条护栏。**
- **费率**: C6 "实付≈nearest-cent, 代码 ceil 过保守" **成立且干净**(88 条全 taker, 0 maker 混入, 有 JSON 佐证)。→ **CONFIRMED。**
- **全局口径病**: O1 已自曝 print gap "大半假象"(quote mid 仅 +1.0pt vs print +7~11pt)。**此警告横跨 C3 h10_tau 表与 C6 favorite +$6.15 —— 两处绝对 edge 数字都是 print 口径, 须打折**。这是九份报告最普遍的**口径混用**风险。
- **B1 OMS 酷刑房(demo 结果 JSON 在场, 已审)**: 8 项 4 FAIL。**两条硬约束采纳前必吸收**: (1) T1 —— demo API **不认服务端 `expiration_ts`**, 止损/退出单必须**客户端自撤**, 不能信服务端到期; (2) T4 —— **分数成交是真的**(fill_count=285.5), 费/PnL/持仓代码须弃整数假设(直连疑点⑤)。另: T5 超卖护栏因建仓失败**实际未测, 须重跑**; demo 成交**不得写 ledger.db**(否则污染 calm 晋升样本, 与疑点③冲突)。

---

## 1. 六疑点逐一裁决

### 疑点① — O2 vs C3 对 #76 的方向语义与金额 —— **CONFIRMED (O2 判反)**

**账本铁证** (`data/ledger.db` id=76, 只读):
| 字段 | 值 |
|---|---|
| side / price / contracts | **NO** / 0.81 / 3 |
| cost_usd / fee_usd | 2.46 / 0.03 |
| result (结算) | **yes** |
| pnl_usd (hold 到结算) | **-2.46** |
| exit_type | hold |

**C3 复算** (`c3_stop_events.csv` #76): `true_death=1, disloc_class=SPOT-MOVE, pnl_usd_hold=-2.46, held_bid_rest=0.46, gross_gain low/mid/high=0.36/0.7152/0.72`。

**三个量各说什么 (指挥要的"口径对齐")**:
1. **-$2.46** = 持有到结算的实际亏损(指挥引用值)。因 NO 持仓遇 result=YES → NO 归零。**这是最差结局。**
2. **C3 的 $0.36-$0.72** = *WS 提速*止损相对 REST 慢止损**多省下的钱**(把出场 bid 从盲区中点救到 0.46 一线的那部分)。C3 把 #76 正确当作"真死单, 快止损省钱"。
3. **裸止损实际亏损** = 卖 3@0.46 = 3×(0.46−0.81) = **−$1.05**。比 hold(−$2.46)**好 $1.41**。

**O2 错在哪**: O2 §2.3 写 "#76 ... 最终 settled=YES ... 双条件持有 → 结算收 $3, 相对救回 ~$1.62"。
- (a) 把 `settled=YES` 误当我方 NO 侧**赢**。实则我方持 NO, YES 结算 = 收 **$0** 不是 $3;
- (b) 声称"双条件持有相对裸止损救回 $1.62"—— **方向彻底反了**: 对 #76, 持有是最差(−2.46), 裸止损才省钱(−1.05)。#76 **不是**"赢家被割"的例子, 是"真死单, 止损(含裸止损)本身就对"的例子。

**谁对**: **C3 对**(#76=真死、止损省钱)。O2 的**结论方向(裸价格阈值不可单独作止损、贴线区靠驻留裁决)本身仍成立**——但它援引的 #76 反例是错的。真正能证明"裸止损=提款机"的应是"**真赢但盘口被砸穿**"的样本;`stop_shadow` 3 条触发(#74 赢/止损也划算、#76 真死、#88 真死)里**没有这种样本**。故该论点当前只有机制推演, 无实测。
> 注: #88 (side=YES, result=NO, true_death=1) 同为真死单, 也非赢家被割。O2 把 #76/#88 都当"贴线未穿的赢家"叙述有误; 二者 spot proximity 分别 +0.0215%/+0.0061% 属实, 但**结算都是死**。

**动作**: 已 `spawn_task` 挂"修正 O2 报告 #76 方向错误"(task_92232128), 建议采纳前先修 O2 该段。

---

### 疑点② — C3 "tau 优势=窗口肥" vs O1 "净 edge 随 tau 升、挪扫描点" —— **BOTH-VALID, 不矛盾, 有净含义**

**两组数字一致**(不是打架):
- C3 `c3_h10_tau.csv` net_cents 随 tau **单调升**: (2,4]+4.74c → (12,14]+13.9c。
- O1 独立算: τ2-4 +4.94c → τ12-15 +9.36c。**同形状**(小差异来自 favorite-frame 与费口径细节)。
- C3 `c3_h10_delay.csv`: **同一 tau 桶内**, 0-30s vs 60-120s discovery-delay 增益仅 **0-1.2pt**。

**组合后对 h10 扫描策略的净含义**(这是指挥要的):
1. **主 edge 来自"在 tau 曲线哪一段入场"(窗口位置), 不来自"WS 早发现固定-tau 机会"**。跨 tau 落差 ~+9pt ≫ 同桶发现延迟 ~1pt。→ 二者结论**方向一致**。
2. **可操作**: O1 建议把 h10 扫描点从 9.7/6.7 上移到 ~11.5/13.5(高 tau 限 ETH/SOL, BTC15M 高 tau 死书)—— 这是"**主动把扫描点搬到肥窗口**", 与 C3 结论**兼容**。C3 只是警告: 别把这套增益归因于 WS 早发现, 也别为 WS 早发现单独付费。
3. **唯一需并读的张力(非矛盾)**: C3 提醒 tau 曲线的肥是**窗口位置/幸存者效应**(只有一直是 favorite 的票才活到高 tau 打印), 所以"挪扫描点"能否**足额兑现** +9pt 有存疑 —— 搬晚了可能吃到的是幸存者偏差残值, 不是纯 alpha。O1 自己也标注这是 **print 代理 + ~9 天平静样本**, 需 quote/L2 因果分离。→ 两报告**都挂了同一免责**, 无冲突。

**净裁决**: 采纳 O1"挪扫描点吃高-tau 窗口"作**提案**(限 ETH/SOL), 同时采纳 C3"**不为 WS 早发现付费**"。两者合起来 = *时窗右移是免费午餐(改扫描时点), WS 早发现不是*。

---

### 疑点③ — C5 MC 门(全 calm 分布)+ C4 跨体制门 叠加后, 2026-09-01 前有门能过吗 —— **如实,非过严;但两层测的是不同东西,不该叠成单门**

**58 天窗口** (2026-07-05 → 09-01)。

**C5 收紧后的单看阈值**(`c5_mc_results.json`, q99 net = 1% 单看假通过所需净值):
| 门 | 当前均值 / n | 收紧阈值(q99) / 所需 n | pre-Sept 可行性(calm-only) |
|---|---|---|---|
| h10_main (fast n=150) | +9.55c / 17 | **+5.11c** / 150 | **有望**: 均值远超阈值; n=150 calm 在 58 天可攒(限 ETH/SOL) |
| h13_final6 | +2.30c / 4 | **+2.32c** / 150 | 勉强(阈值几乎贴均值, 且 n=4→150 太远) |
| hourly_favorites | +1.02c / 53 | **+3.74c** / 300 | **难**: 当前均值 +1.02c ≪ 阈值 +3.74c |
| h12_book_only | −44c / 3 | +6.75c / 40 | 不可能(当前负 EV) |
| h15_maker (EV-only) | n=0 | +16c / 20 | 阻塞: 无 shadow 分母, 队列门不可复算 |

**C4 跨体制门**(全天候 live 前提): elevated settled **n≥30** AND storm settled **n≥10**, 各自独立过门。
**当前体制存货**: crypto evidence 135 行 → **calm 131 / elevated 4(全来自已判死 legacy) / storm 0**。

**storm 样本能否在 58 天攒够 10 个 in-band 结算胜**(我的估算):
- 15m 结算 ~86/天, 0.84-0.94 in-band 占 20% → ~17 in-band/天(**全体制**)。
- storm 占**时间**上限 <10%, 且**跳跃税把 storm 分钟的价推出 0.84-0.94 带**(favorite 在暴动中变刀口)。
- 乐观 10%-storm 情景 ~101 storm-tagged in-band/58 天, 但要**干净 settled 胜**才过门, 现实远低于此; 悲观 2% 情景仅 ~20。→ **storm n≥10 的干净样本在 58 天前基本攒不齐, 全天候晋升 pre-Sept ≈ 不可能。**

**裁决建议(给指挥)**: **不是过严,是如实 —— 但两层不该叠成一个 pre-Sept 门。**
- C5 的 MC 门回答"**calm edge 是真的还是多重检验噪声**";C4 的跨体制门回答"**它能不能扛暴动**"。二者**逻辑正交**。
- **应 AND 只用于"全天候 live";calm-only live 路径应独立开着**。蓝图自己的推进顺序(纯采集≥7 天 → quote 重审 → 才谈时敏)已隐含 calm-first。
- **落地**: (1) 采纳 C5 q99 MC 阈值作 **calm-only GO 门** → h10 有望 9 月前过, 允许 calm-only 放量; (2) C4 全天候门作**独立的、更晚的里程碑**, 不阻塞 calm-only。**把两门叠成"9 月前必须跨体制过"= 过严, 会白白冻死一个已接近可晋升的 calm 通道。**

---

### 疑点④ — 事件驱动快照 + 死盘降频, 对 O1 |z| 研究 与 O2 驻留验证够用吗 —— **够用, + 1 条护栏**

**背景**: C2 实测 SQLite DB **14.392 GB/day**(raw gzip 另 0.548 GB/day), 蓝图 raw 硬帽 500MB/day、DB 无帽。指挥拟"事件驱动快照 + 死盘降频"压容量。

**对 O1 |z| 研究(够用)**: |z| 研究要的是**在选定 τ 点采样** spot + Kalshi mid 算 |spot−strike|/(σ√τ)。这是**采样问题**, 从 delta 日志 `book_at(ticker, ts)` 重建即可。事件驱动不影响。

**对 O2 驻留(dwell)验证(够用, 因为事件驱动=驻留的原生表示)**:
- `dwell_ms(ticker, predicate)` 要"谓词已连续为真多少毫秒", 需**连续 top-of-book 时间线**。
- **关键洞察**: WS `orderbook_delta` **本身就是事件驱动的, 每次 top-of-book 变化都发一条 delta**(C1 实测 seq 连续、无缺口)。因此"**无事件 = 无变化 = 书保持**", 驻留可从事件流**无损重建**。事件驱动**不破坏**驻留, 反而是它的原生编码。C2 实测 34.5 delta/mkt/min 均值, 活跃市场事件密度充足。

**唯一真风险 = 死盘降频的盲区(不是事件驱动本身)**:
- 若某市场被降到低频, 之后**突然被猎杀**(6 秒内假摔-回填), 存储有空档 → 驻留读到 stale book → 判定失真。
- **护栏(必须加)**: **任一 ticker 收到 delta 立即重开满速**;只对"N 分钟零 delta"的真死书降频。死书一旦醒来, 第一条 delta 就重新武装。以 34.5 delta/mkt/min 计, 活跃市场永不降频, 只有真死书降频。
- **附带收益**: 死盘降频正好砍掉 14.4GB/day 的主成本(大量死书的 1s 全簿快照), 而 O2 §4 要的双侧深度/撤单事件/现货对齐时钟对**活跃**市场保留满速即可。

**裁决**: 方案**够用**, 但把"死盘降频"的护栏(delta 即重武装 + 仅对零-delta 死书降频)**写进 tickstore 采集协议**, 否则驻留在被猎杀的瞬间会瞎。

---

### 疑点⑤ — C6 "实付≈nearest-cent, 代码 ceil 过保守" 的对账口径是否干净(是否混入 maker fee=0 行)—— **CONFIRMED, 干净**

**C6 自证** (`c6_fee_summary.json`): `live_nonvoid_rows=88, live_taker_nonvoid_rows=88, live_maker_nonvoid_rows=0`。→ **88 条全 taker, 0 maker 混入**, 直接回答疑点。
`actual_fee_sum=1.23, raw_fee_sum=1.149832, ceil_formula_sum=1.51, nearest_cent_sum=1.22, ceil_exact=60/88, nearest_exact=85/88`。

**我的独立重建** (`data/ledger.db` 全表, 只读):
- live 非 void = 93 行(比 C6 的 88 多 5)。差额来自 C6 额外剔了非-taker/分数张/手动测试行(如 id=102 h15maker、id=86 的 0.4 张 weather-fade、manual order-path test)。**剔法合理**。
- 全 93 行: actual=$1.28, ceil=$1.59, nearest=$1.28, exact_ceil=62/93, exact_near=89/93。**方向与 C6 一致**: actual 远近 nearest, ceil 高估。
- 发现 6 条 fee==0 行, 其中 **id=25/27/32 是 favorite taker @0.93-0.95** —— 这三条**在 C6 的 88-taker 集内**(它们是 taker、非 void、非 maker)。它们付 $0 是因为 raw fee ≈ 0.4c 被**截断/豁免为 0**(Kalshi 对亚分费的处理), raw≈0.4c → nearest 0c → actual 0c, **合法算作 nearest 命中**, 不制造假结论。

**裁决**: C6 结论 **CONFIRMED 且口径干净**。一条**加强注记**: 机制不是"四舍五入到分", 而是"**Kalshi 对小单亚分费截断/豁免**"(对 1-2 张小单甚至比 nearest 更省)。C6 建议(报告同时输出 actual_fee 与 ceil_fee、别把 $1 小单按 ceil 灾难化)**照采**。

---

### 疑点⑥ — B1 席 OMS 酷刑房 —— **已审 (b1_report.md 无, 但 demo 结果 JSON 在场; 4 FAIL 需处置)**

`b1_report.md` 未出现, 但 **`GAP/b1_run1_demo_gym_results.json` 在场**(demo env, base=demo-api.kalshi.co, clean_exit=True, elapsed 223s, 8 项酷刑)。既然指挥要求"若出现则审", 我不盲跳。逐项(全 demo, 我未下任何单, 只读该 JSON):

| 项 | 结果 | 含义 | 伤钱等级 |
|---|---|---|---|
| **T1 expiry echo** | **FAIL** | 下单带 `expiration_ts` 但 `expiry_echo=False`, 单到期后仍 `resting`, `auto_inactive=False` —— **demo API 不认/不回显到期字段** | **高**: OMS 若靠服务端 `expiration_ts` 自撤止损/退出单, 单会永久挂着 → **止损必须客户端自撤, 不能信服务端到期** |
| **T2 双撤幂等** | **FAIL** | 首撤成功(单已消失), 对同 id 二次撤 → HTTP 404 not_found | **中**: 这其实是交易所正常语义; 但 OMS 必须把"撤单 404"当**已撤成功**处理, 否则重试循环会崩(cleanup_errors=2 正是此因) |
| **T3 撤-成交竞速** | PASS | 10 次竞速 **fill_before_cancel=10, cancel_won=0** | — 佐证 O2:**追不上快成交**; 支持"驻留确认后再武装"而非事后撤 |
| **T4 部分/分数成交** | PASS | 999@0.33 → **fill_count=285.5(分数!)**, remaining=0, 干净 | **高(数据契约)**: **分数张成交是真的**。直连疑点⑤(ledger id=86 的 0.4 张)—— OMS 与费/PnL 代码**必须处理分数 fill_count**, 否则整数假设会错算持仓/费 |
| **T5 超卖保护** | **FAIL** | 但 evidence=`entry did not fill` → **是建仓失败导致测试没跑起来, 不是已证 OMS bug** | **未验证**: "卖超过持仓量"的护栏仍**未测**, 必须重跑 |
| **T6 限速** | PASS | 60.8s 内 240 次 place/cancel, **first_429=None** | — 限速有余量, 支持疑点④满速采集可行 |
| **T7 重复 coid** | PASS | 重复 client_order_id → **HTTP 409 order_already_exists 拒绝** | — 幂等键有效, 防重下 |
| **T8 私有 WS** | SKIP | 预算 + 仓库无私有 WS 鉴权实现 | — |

**裁决**: B1 酷刑房**有真发现, 非无事**。**T1(服务端到期不可信)与 T4(分数成交)是采纳前必须吸收的两条硬约束**; T2 需把撤单 404 当成功; **T5 超卖护栏未验证, 必须重跑**(建仓先用会成交的价/量, 否则 gym 每轮都测不到最关键的护栏)。全程 demo, 无真钱暴露。另建议后续补: 下单-确认往返延迟日志(O2 §4 抖动前提)、demo 成交**不得**写进 `data/ledger.db`(否则污染 calm 晋升样本, 与疑点③直接冲突)。

---

## 2. 重验数字表 (抽查, 全部用复算脚本/只读 DB 独立重跑)

| # | 报告 | 原始声明 | O3 重验 | 判定 |
|---|---|---|---|---|
| 1 | O2 | #76 双条件救回 $1.62、settled=YES 收 $3 | ledger id=76: NO/结算YES/hold −$2.46; 裸止损 −$1.05 | **驳(方向反)** |
| 2 | C3 | #76 gross_gain 0.36-0.72、真死 | c3_stop_events.csv 逐列吻合; ledger 佐证 pnl_hold=−2.46 | **符** |
| 3 | C3 | h10 tau net 随 tau 升 4.74→13.9c | c3_h10_tau.csv 逐桶吻合 | **符** |
| 4 | C3 | 同桶发现延迟增益 0-1.2pt | c3_h10_delay.csv: (2,4] 0-30s 6.9 vs 60-120s 6.4=0.5pt 等吻合 | **符** |
| 5 | O1 | net edge 随 tau 升 τ2-4 +4.94c→τ12-15 +9.36c | 与 C3 同形状(小差异=口径) | **符(口径注)** |
| 6 | O1 | \|z\|≥1.5 → p_favwin≥0.994 (τ<60min) | O1 §2 表: 1.5-2.5 桶 τ0-60 全 ≥0.994; AUC 0.988-0.999 | **符** |
| 7 | O1 | print gap 大半假象, quote mid 仅 +1.0pt(τ≤15) | O1 自证 1327 行 quote 快照; **横跨 C3/C6 的 print 数须打折** | **符(关键口径)** |
| 8 | C5 | 门族至少一门假通过 84.14% | c5_mc_results: core family false_any_pass=0.8414 | **符** |
| 9 | C5 | H10 n=14 全胜+≥9.7c 零假设 8.69% | c5_mc_results special: 0.0869 | **符** |
| 10 | C5 | H15 20 fills EV>0 假通过 ~60% | c5_mc_results: h15_maker false_pass=0.5997 | **符** |
| 11 | C4 | crypto evidence 135: calm131/elev4/storm0 | regime_summary 佐证; storm=0 是疑点③关键 | **符** |
| 12 | C4 | 下一 FOMC minutes 07-08 18:00Z, CPI 07-14 12:30Z | econ_calendar 佐证 | **符** |
| 13 | C6 | 88 taker/0 maker, actual $1.23 vs ceil $1.51 | c6_fee_summary.json 逐字段; 独立重建同向 | **符(干净)** |
| 14 | C2 | DB 14.392 GB/day, raw 0.548 GB/day | c2_analysis json 佐证; 疑点④主成本 | **符** |
| 15 | O2 | 回填中位 5.55s, dwell=8s 滤 52% 假摔 | C3 recovery_curve: p50 落在 10s(.53)-30s(.80) 间≈9-10s; O2 empirics 用 disloc/stop 子集得 5.55s。两者口径不同但同量级 | **符(口径注)** |

---

## 3. 采纳建议总表 (按对钱影响排序)

| 优先 | 来源 | 建议 | O3 裁决 | 理由/前提 |
|---|---|---|---|---|
| P0 | O2 | #76 作"裸止损割赢家"反例 | **驳回(须修正)** | 方向反; #76 是真死单, 止损省钱。修正后其"裸价格不单独作止损扳机"原则仍**修正后采纳** |
| P0 | C5+C4 | 把 MC 门与跨体制门叠成 pre-Sept 单门 | **驳回(过严)** | 全天候 9 月前不可能(storm=0); 会冻死接近可晋升的 calm 通道 |
| P0 | C5 | q99 MC 阈值作 **calm-only** GO 门 | **采纳** | h10 均值(+9.55c)远超阈值(+5.11c), n=150 可攒; 堵住 84% 家族假通过 |
| P1 | C4 | 跨体制门作**独立较晚里程碑**(elev≥30/storm≥10) | **修正后采纳** | 不作 calm-only 阻塞门; 作全天候前置 |
| P1 | C4 | storm/macro overlay 隔离协议(15m 全影子、favorites 降 x1、stop proximity 扩 ±0.10%) | **采纳** | 预注册纪律干净; 唯一提醒: proximity 扩大会增假退出(卖飞), 但 calm 样本证据链完整 |
| P1 | C3 | 现只建**只读** WS/L2 采集, 不接 live 触发; bankroll≥$100 或 stopshadow n≥20 且真死 precision≥80% 再议 | **采纳** | 与蓝图"证据先到毫秒级"一致 |
| P1 | O2 | dwell=8s 驻留过滤 + 6s 死亡线下限 | **采纳(参数待放大 n 复核)** | 机制对; 但 n=3 触发、5.55s 中位靠子集, O2 自标"提案冻结非终值" |
| P2 | O1 | h10 扫描点右移到 ~11.5/13.5(限 ETH/SOL) | **修正后采纳(提案)** | 吃高-tau 肥窗是免费(改扫描时点); 但须附幸存者偏差 + print≠quote 打折 |
| P2 | O1 | 引擎每笔记 \|z\|, 买热门重述为买 \|z\|≥1.5 尾部保险, 硬拒 \|z\|<0.8 临界单 | **采纳** | AUC 0.99+ 证据强; 低成本高价值的框架升级 |
| P2 | C6 | 费率代码保持 ceil, 但报告/回测同时输出 actual_fee; fee_optimal_contracts 摊薄税 | **采纳** | 干净; 降成本不加风险 |
| P2 | C6 | h15 20 笔门加记 fill-conditioned win-rate discount(劣化>2pp 则 maker 没赢过 taker) | **采纳** | 补 C5 指出的"H15 队列门不可复算"缺口 |
| P2 | 蓝图 | 事件驱动快照 + 死盘降频 | **采纳 + 加护栏** | 护栏: 任一 delta 即重开满速, 仅对零-delta 死书降频(否则驻留瞎) |
| P3 | C2 | tickstore 与 quant_loop 完全隔离, 降级回 REST 无条件兜底 | **采纳** | 采集永不阻塞真钱退出 |
| P3 | C5 | 加 event_id/gate_label/H15 shadow 分母(分析层 event_key JOIN 规范) | **采纳(治理)** | 不改交易逻辑, 堵数据库层双计漏洞 |
| — | C1 | WS 端点/鉴权/seq 规则实测定谱 | **采纳(事实底座)** | seq_gaps=[], 支撑疑点④的"delta 无损重建驻留" |
| P0 | B1 | OMS 依赖服务端 `expiration_ts` 自撤单 | **驳回** | T1 FAIL: demo 不认到期字段, 单永挂; 止损须**客户端自撤** |
| P0 | B1 | 费/PnL/持仓代码假设整数张 | **驳回(须改)** | T4: 分数成交(285.5)是真的; 直连疑点⑤; 整数假设会错算 |
| P1 | B1 | 撤单 404 视为错误 | **修正后采纳** | T2: 404-on-cancel=已撤成功, 否则重试崩(cleanup_errors=2) |
| P1 | B1 | 超卖护栏(T5)已验证 | **需重跑** | T5 FAIL 因建仓没成交, 护栏实际**未测**; gym 重跑用可成交价/量 |
| — | B1 | demo 成交写入路径 | **红线** | demo fill **不得**进 ledger.db, 否则污染 calm 晋升样本(冲突疑点③) |

---

## 4. 互相打架 / 口径混用清单 (同一参数不同建议 或 数字冲突)

1. **#76 语义冲突 (已裁, 疑点①)**: O2(赢家被割/救回$1.62) vs C3(真死单/省$0.36-0.72) vs 账本(−$2.46)。**C3+账本对, O2 错。**
2. **stop proximity 阈值三处不一 (需指挥统一冻结)**:
   - O2 §5g-2: ±0.05% 贴线(机械扳机基线);
   - C4 elevated: ±0.075%; C4 storm: ±0.10%;
   - 三者不冲突(是 calm/elevated/storm 的**分档**), 但**当前无单一权威表**。→ 建议指挥出一张 `proximity(regime)` 冻结表, 否则实现时易取错档(伤钱: 取窄了在 storm 卖飞赢家, 取宽了漏判真死)。
3. **print vs quote 口径混用 (最普遍, 疑点②/⑦)**: C3 h10_tau(+4.74~13.9c)、C6 favorite(+$6.15/90 张)、C4 门级均值 **全是 print 代理**;O1 自证 quote mid gap 仅 +1.0pt(τ≤15)。**这些绝对 edge 数字不能当可兑现 EV, 只能作跨-τ 相对形状**。→ 采纳任何"绝对 edge"数字前必须标注 print≠fill 折扣。**这是九份报告最系统性的伤钱风险**(会高估所有通道盈利能力)。
4. **H12 命名冲突 (C5 已点名, 未解)**: `disloc.py` code gate = `BOOK-ONLY n≥40 EV≥+8c`;注册簿/SHORTCYCLE 后文 = `SPOT-MOVE n≥40 EV≥+5c`。C5 MC 两个都算(book_only 假通过 0.19%, spot_move 24.73%)。**不冻结命名 → 复盘可选择性引用好看的一边。** → 建议冻结: 哪个是 live proposal 门必须唯一。
5. **WS 价值口径 (C3 内部自洽, 但需对齐 O2)**: C3 说当前 $16 账户 WS 仅止损提速值 $4.1-34.7/周(n=3 极不稳);O2 说 WS 价值 = "8s 驻留确认后仍在场执行止损/接修正"。**两者是同一件事的成本侧与收益侧**, 不冲突, 但报告未交叉引用。建议合并陈述: WS≠追坑 alpha, WS=驻留确认后仍能执行退出的期权, 值不值看止损+接修正两通道的量(当前量太小)。
6. **样本量外推标注 (通查)**: C3 stop 周化 $4.1-34.7/周 **明标 n=3 频率置信度低**(合规);C5 所有门 **明标 n 与 MC_SE**(合规);O1/C4/C6 绝对 edge **均标 ~9 天平静样本**(合规)。**唯一未充分标注的是 O2**: 死亡线 n=81(6 天)、三条 0.70 触发 n=3、5.55s 中位来自子集 —— O2 §6 有免责但正文参数(dwell=8s/6s 下限)读起来像终值。→ 采纳 O2 参数时须并读 §6"提案冻结非终值"。

---

## 5. 复算证据锚点 (供指挥抽验)

- 只读 DB: `data/ledger.db`(trades n=108, id=76 铁证)、`data/stop_shadow.db`(stops n=5)。
- CSV/JSON: `c3_stop_events.csv`(#76 逐列)、`c3_h10_tau.csv`、`c3_h10_delay.csv`、`c3_backfill_recovery_curve.csv`、`c5_mc_results.json`(门级 false_pass + q99 阈值)、`c6_fee_summary.json`(88 taker/0 maker)、`regime_summary.json`、`econ_calendar.csv`。
- 脚本: `c3_ws_value.py`、`c5_monte_carlo.py`(seed=24505, reps=10000)、`c6_fee_capacity_analysis.py`、`empirics.py`(O2)、`p2_spot_distance.py`(O1 |z|)。
- B1: `GAP/b1_run1_demo_gym_results.json`(run_id=dgf8eb0dba, demo, 8 项酷刑, T1/T2/T5 FAIL、T4 分数成交 285.5、T3/T6/T7 PASS)。

---

```json
{
  "seat": "O3",
  "status": "OK",
  "key_findings": [
    "疑点①CONFIRMED: O2把#76判反——账本(ledger id=76)铁证#76是NO持仓/结算YES/归零, hold亏$2.46, 裸止损反而只亏$1.05; C3(真死单/WS提速省$0.36-0.72)对, O2的'裸止损割赢家/救回$1.62'错, 且'裸止损=提款机'当前无真实赢家样本支撑, 已挂修正任务。",
    "疑点②BOTH-VALID不矛盾: C3'tau优势=窗口位置'与O1'净edge随tau升'一致(net 4.74→13.9c, 同桶发现延迟仅0-1.2pt); 净含义=可挪扫描点到高tau吃肥窗(免费, 改时点), 但别为WS早发现付费(只值~1pt)。",
    "疑点③如实非过严但两层不该叠: C5的MC门(测calm edge真伪, h10均值+9.55c远超q99阈值+5.11c可望9月前过)与C4跨体制门(storm settled n≥10, 当前storm=0, 58天前基本不可能)逻辑正交; 建议采C5作calm-only GO门, C4作独立较晚里程碑, 叠成pre-Sept单门=过严会冻死可晋升的calm通道。",
    "疑点④够用+1护栏: 事件驱动快照对O1的|z|采样和O2的dwell都够用(WS delta本身事件驱动, 无事件=无变化, 驻留可无损重建); 唯一红线是死盘降频盲区, 必须加'任一delta即重开满速、仅对零-delta死书降频'护栏否则被猎杀瞬间驻留瞎。",
    "疑点⑤CONFIRMED且干净: C6的88条全taker/0 maker混入(c6_fee_summary.json自证), 实付≈nearest-cent/代码ceil过保守成立; 独立重建同向(actual$1.28 vs ceil$1.59, nearest命中89/93 vs ceil命中62/93); 机制实为Kalshi对亚分费截断/豁免。",
    "最系统性口径病: print vs quote混用横跨C3 h10_tau/C6 favorite+$6.15/C4门级均值(全print代理), 但O1自证quote mid gap仅+1.0pt(τ≤15); 所有'绝对edge'数字须打print≠fill折扣, 只能作跨τ相对形状, 否则高估全通道盈利。",
    "未解冲突需指挥冻结: (a)stop proximity三档±0.05/0.075/0.10%无单一权威表; (b)H12门命名BOOK-ONLY+8c vs SPOT-MOVE+5c不一致(C5已点名); (c)O2参数(dwell8s/6s下限)读起来像终值但实为n=3/n=81子集提案。",
    "疑点⑥已审(b1_report.md无但demo结果JSON在场): OMS酷刑8项4 FAIL, 两条硬约束必吸收——T1服务端expiration_ts不可信(单永挂, 止损须客户端自撤)、T4分数成交真实存在(fill_count=285.5, 直连疑点⑤, 费/PnL/持仓须弃整数假设); T2撤单404须当成功, T5超卖护栏因建仓失败实际未测须重跑; 另立红线: demo成交不得写ledger.db否则污染calm晋升样本。全程DB只读、未下单、未改仓库文件、未碰secrets、遵守全部铁律。"
  ],
  "recommendation": "采纳前先修O2的#76反例(方向反); 把晋升法分两层——采C5的q99 MC阈值作calm-only GO门(h10有望9月前过)、C4跨体制门降级为独立较晚里程碑(勿叠成pre-Sept单门=过严); 蓝图事件驱动快照够用但必须加死盘降频护栏(delta即重武装); C6费率结论与O1的|z|框架采纳; 全庄园强制标注print≠quote折扣于任何绝对edge数字; 冻结proximity(regime)表与H12门唯一命名; OMS吸收B1两条硬约束(止损客户端自撤不信服务端expiration_ts、费/PnL/持仓弃整数假设支持分数成交)并重跑T5超卖护栏、隔离demo成交不进ledger.db。"
}
```
