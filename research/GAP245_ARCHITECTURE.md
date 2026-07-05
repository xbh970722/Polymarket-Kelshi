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

## 分工契约 (长期有效)

| 角色 | 职责 | 不许 |
|---|---|---|
| Fable 5 | goal/架构/API契约/库选型/冻结参数/终审代码/注册簿立法 | 绕过用户专属杠杆 |
| Codex xhigh | 按 spec 施工 (含函数签名级遵从)、对我的设计找错、测量研究 | 自行更改架构/参数 |
| Opus 4.8 | 对抗性红队、方法论审计、测量研究 | 同上 |

Seats 产出一律 提案/实现, 采纳/合并权在 Fable; 涉钱参数最终权在用户。

## 当前施工队列

1. [进行中] C1-C6 + O1/O2 测量报告 (本文件的喂数轮)
2. [报告落地后] 我修订本文件数字 → 发 tickstore/regime 施工 spec → codex 施工
   + opus 红队 → 我终审合并
3. [7 天采集后] quote 口径重审全部在审门 (预期最痛也最值的一步)
