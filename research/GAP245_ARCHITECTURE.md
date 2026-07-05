# GAP-245 总架构 (Fable 5 主设计, 2026-07-05)

指挥关系 (用户令): Fable 5 定 goal/大方向/代码架构/库选型; Opus 4.8 与 Codex
5.5 xhigh 按此实现并挑错。本文件是施工的唯一蓝图 — seats 的报告是给它喂数的,
数字落地后由我修订冻结, 不由 seats 自行发挥。

## GOAL (90 天)

把系统从 "分钟级轮询 + 单一平静体制证据 + 零售 taker 费率" 升级为:

1. **秒级数据底座** — tick 采集 → 全部门的证据从 print 口径升级为 quote 口径
2. **体制感知** — 每条证据带 calm/elevated/storm 标签, 晋升须跨体制或明示限定体制
3. **maker 优先费率结构** — 费=0 的挂单形态成为默认候选, taker 只留给时敏机会

约束不变: 预注册门先于数据、影子先于实盘、美元帽只有用户能加、C-C 冻结期内
不开 15m 新交易枝 (数据/防御基建不属交易枝)。验收标准: 证据质量与执行质量
达到 "能承接 $1000 账户" 而纪律零松动。

## 第一层: 数据底座 (tickstore)

**部件**: `src/tickstore.py` (库) + `scripts/tick_daemon.py` (独立守护进程)。
与 quant_loop 完全隔离 — 采集永不阻塞交易, 交易永不依赖采集进程活着 (降级回
REST 轮询是无条件兜底)。

**库选型 (定)**: `websockets` (asyncio 纯 py); json 用 stdlib (orjson 有则用,
不强依赖); 存储 SQLite WAL, 不引入新 DB 引擎 — 庄园同构性优先。

**存储 schema (定)**: 日分区文件 `data/ticks/YYYYMMDD.db` (gitignore, 同
backfill 惯例), 两表:

```sql
book(ts_ms INTEGER, ticker TEXT, seq INTEGER,
     yes_bid_c INTEGER, yes_ask_c INTEGER,       -- 顶档, 分
     bid_depth INTEGER, ask_depth INTEGER,        -- 顶档量 (fp*100 取整)
     l2 TEXT,                                     -- 前3档 JSON
     PRIMARY KEY (ticker, ts_ms, seq))
trades(ts_ms INTEGER, ticker TEXT, px_c INTEGER,
       count_fp REAL, taker_side TEXT)
```

原始消息旁路存 `data/ticks/raw_YYYYMMDD.jsonl.gz` (重放/审计用), 单日硬帽
500MB, 超帽自动降为仅 book 表。

**采集协议 (定)**: 订阅=snapshot+delta; seq 断档→重订阅重建; 心跳 10s;
断线指数退避 1→60s (Windows 睡眠唤醒自愈); 单实例 pid 锁; 活跃市场集每 5min
由 REST 发现 (四币 15m 当前窗 + 最近两个小时盘)。

**消费 API (定, 这是防御层的地基)**:

```python
tickstore.latest_book(ticker) -> Book | None      # None = 采集不在, 调用方回退 REST
tickstore.book_at(ticker, ts_ms) -> Book | None   # 历史重放
tickstore.dwell_ms(ticker, predicate) -> int      # 谓词已连续为真多少毫秒
```

`dwell_ms` 是反猎杀的一等原语: "bid≤0.70 已持续 N ms" 而非 "此刻 bid≤0.70"。
6 秒假摔 (disloc 实测 52%) 在 dwell 面前自动隐形。

**推进顺序 (定)**: 纯采集跑 ≥7 天 → 用 quote 数据重审全部在审门 (print→quote
升级, 预期部分门的均值要缩水 — 这是买真相) → 之后才谈任何时敏逻辑, 且仍受
C-C 冻结与 VALUES 5e 行权顺序约束。**毫秒级执行不在本期 goal 内**: 先让证据
到毫秒级, 执行等证据说话。

## 第二层: 体制感知 (regime)

**部件**: `src/regime.py`。API (定):

```python
regime_at(ts) -> "calm" | "elevated" | "storm"    # 只用 ts 之前的数据, 防前视
```

阈值由 C4 的 90 天校准喂数, 我冻结后写死 (预期形态: 滚动24h实现波动率百分位
<60/60-90/>90)。经济日历表 `data/econ_calendar.csv` (CPI/FOMC/NFP/PCE, ET 时刻,
VERIFIED/UNVERIFIED 分级) 由 C4 产出, 每季由反思任务续表。

**证据法修正案 (定, 属证据加严=降风险, 即时生效)**:
- 各影子采集器 INSERT 起加 regime 列 (加列不改行为, 采集器非钱路径)
- 每个门的 report 行按体制分解展示
- **晋升双门槛**: 统计门通过 且 (优势在 ≥2 体制成立 或 门明示 "仅限 X 体制
  且该体制可实时识别")。风暴日协议按 C4 草案由我定稿, 用户有否决权。

## 第三层: 费率与规模 (maker-first)

- `kalshi_client.fee_optimal_contracts(price, budget)` (定): 选择使 ceil 税率
  最小的张数 (1 张 90c 的 ceil 税 +59%, 张数摊薄曲线由 C6 喂数)。favorites/
  h10 的 sizing 接入它 — 属降成本不加风险, 我批
- maker 化路径不变: h15 的 20 笔门是唯一仪器, 过门则由我出各通道 maker 变体
  设计; 不过门则 taker 形态维持 + 费率税认命
- 资金边际价值曲线 (C6 喂数) 进周报; 充值与否永远是用户的按钮

## 第四层: 反猎杀 (防御做进基建而非通道代码)

O2 交分类学与参数建议, 机制由我定 (已定的三件):
1. `dwell_ms` 原语 (上文) — 所有快信号必须声明驻留窗
2. **现货确认延迟预算**: 确认信号 (Coinbase) 比诱饵 (Kalshi 簿) 慢是结构事实
   → 系统存在一条 "不抢 <X 秒机会" 的硬线, X 由 C1/C2 实测两路延迟后我冻结
3. **不可预测性**: 反应延迟加抖动、非固定单量 — 进 tickstore 消费层的默认参数,
   不留给各通道自选

## 第五层: demo 靶场 (用户 07-05: "demo 环境下激进一点")

**现实勘察 (07-05 实测)**: demo 不镜像生产行情 — crypto 阶梯不存在 (15m 冻在
5 月, 时薪盘只有怪 strike), 多数簿是空的, 少数电竞/体育盘有 demo bot 报价。
**因此 demo 的证据等级永远是 D 类 (机制类), 不进任何优势门** — 在 demo 里
"赚了假钱"不构成任何晋升证据, 这条防的是自欺。

**demo 的正确用法 = OMS 酷刑房, 激进到底**:
- 目标清单 (机制门, 每项过/不过):
  1. expiration_ts 往返 (生产至今未实测! demo 可当天答案)
  2. GTC 挂单全生命周期: 挂/改/撤/过期/部分成交/撤单竞速 (h15 的 4 个已修
     竞态各造一次, 验证修复真的兜住)
  3. reduce_only 边界 (F3 类), 超余额 fills-to-cash 行为复现 (F2 的教训在
     demo 里免费重放), 小数成交处理
  4. 高频下单节流: 连续 place/cancel 直到限速, 实测 429 行为与恢复
  5. WS orders/fills 私有频道 (C1 只测了行情频道; 成交推送是 OMS 升级素材)
- 载具: scripts/demo_gym.py (施工波交付) — 挑有簿的 demo 市场轰击, 输出
  机制检查表 JSON; 每次 OMS 代码改动后必跑 (新的回归门)
- 弹药: 用户在 demo 站点领假钱 (当前余额 $0, 领完即开轰)

**纪律不放松的地方**: demo 凭据同真钱纪律 (不回显不入库); demo 结果与生产
账本物理分离 (不同 DB 前缀); "激进"只指机制探索的火力, 不指绕过证据分级。

## 分工契约 (长期有效)

| 角色 | 职责 | 不许 |
|---|---|---|
| Fable 5 | goal/架构/API契约/库选型/冻结参数/终审代码/注册簿立法 | 绕过用户专属杠杆 |
| Codex xhigh | 按 spec 施工 (含函数签名级遵从)、对我的设计找错、测量研究 | 自行更改架构/参数 |
| Opus 4.8 | 对抗性红队、方法论审计、测量研究 | 同上 |

Seats 产出一律 提案/实现, 采纳/合并权在 Fable; 涉钱参数最终权在用户。

## 喂数轮终裁 (2026-07-05, 十席全毕: C1-C6 + O1-O3 + B1)

**数字冻结** (证据: scratchpad gap245/ 十份报告, O3 交叉复验):
- tickstore: WS 生产端点/鉴权/seq 语义实测可用 (C1); 380 msg/s / 652 ticker /
  CPU 11% 单核 / seq 零断档 (C2 十分钟验收)。**快照改事件驱动** (簿变才写) +
  O3 护栏: **任一 delta 立即恢复满速, 仅零活动死书降频 30s** — 否则被猎杀
  瞬间驻留计时失明。raw 500MB/天帽维持; DB 预期 <1GB/天 (原 1s 全量 14.4GB)。
- WS 接实盘门 (C3): **bankroll >= $100 或 stopshadow n>=20 且真死精度 >=80%**,
  二满足其一再议; H12b taker 复活前置: L2 证明可吃 ask 在 0-10s 内落坑
  (坑半衰期实测 9.4s; 30s 后 EV 转负; REST 节奏吃到的是第 10-16 口)。
- 晋升法拆两层 (O3 裁定, 采纳): **C5 的 MC 校正门 = calm-only GO** (家族
  alpha 0.5%); **C4 跨体制门 = 独立后期里程碑** (全天候 live 需 elevated
  n>=30 + storm n>=10), 不叠成 9/1 前单门。
- 反猎杀 (O2, 经 O3 纠错): **永不抢反应窗 <6 秒的机会** (回填中位 5.55s,
  双峰无中速安全区) + **盘口深度永不作信号** (天然免疫 spoof) — 两条不可改。
  五层防御参数为提案值, 待 tick 数据影子验证。**#76 方向判反已纠**: 裸止损
  割赢家论目前零真实样本, 降级为待验假设。
- 时点 (O1): 状态阈值 |z| 取代钟点; **print 口径热门便宜 +7~11pt 在 quote
  口径只剩 +1.0pt** — print≠fill 折扣条款入注册簿总则; |z| 记录进引擎,
  |z|<0.8 硬拒先影子 n>=50。
- 费率 (C6): 实付≈四舍五入 (nearest 85/88), 代码 ceil 保守留作下单门,
  报告双轨; 0.85-0.94 唯一可辩护核心带; **$16→$50 边际价值最高** (解卡顿
  + 喂 h15 门), 充值权在用户。
- OMS 实测 (B1 酷刑房, demo $2000, 双跑清场归零): **expiration_ts 服务端
  不生效** (130s 后仍 resting!) → h15 崩溃保险作废, mark 撤单纪律为唯一
  保险, 施工波加"循环死→撤全部挂单"看门狗; 撤单竞速 10 连发实测
  fill-before-cancel 占 60-80% (h15 撤后验证机制是对的); 二次撤单 404 =
  终态确认语义; 999 张 fills-to-cash 与小数 fill_count_fp 复现。
  **demo_gym 定为 OMS 回归门**: 每次改单据路径必跑 (scripts/demo_gym.py)。
- 止损贴线带宽单一权威表: **calm ±0.05% / elevated ±0.075% / storm ±0.10%**,
  接 regime 自动切换 (施工波)。

## 当前施工队列

1. [完成] 喂数轮 (十席) + 总立法 (本节)
2. [下一波, codex 按 spec 施工 + opus 红队 + 我终审]:
   ① tick 采集器进驻 (C2 原型 → 我的 schema + 事件驱动快照 + 统一毫秒时钟)
   ② regime.py 进 src/ + 采集器体制列 + 守卫带宽接体制
   ③ |z| 记录 + 硬币区影子旗; ④ 看门狗 (循环死→撤挂单)
   ⑤ schema 三洞 (gate_label / event_key / h15 影子分母); ⑥ 费用双轨报告
3. [7/8 FOMC 纪要] 第一次风暴采样 (宏观窗 T-30m~T+90m 协议生效)
4. [7 天采集后] quote 口径重审全部在审门 (O1 已预告缩水方向)
