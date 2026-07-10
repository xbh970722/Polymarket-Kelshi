# D3 CRYPTO-STRUCTURAL：H16 quote 复算、生产影子与 tickstore 消费层设计

**席位：Codex 5.6-sol（设计/数据）**  
**数据截点：tick 至 2026-07-10 04:40:06Z；可用 BTC/ETH/SOL spot 至 2026-07-09 21:45Z；XRP spot 至 2026-07-06 10:40Z**  
**裁决：HOLD / 不晋升。H16 的 86c proxy EV 仍为正，但完整预注册门未通过。**

本文只设计影子和研究基建。本文不授权下单，不修改 crypto 门、尺寸、zone、`z_floor`、止损、预算或任何实盘参数，不接入 `src/pipeline.py`、`src/live.py`、`scripts/quant_loop.py` 或正在运行的 `ws_capture`/watchdog。最小真实执行探针仅是 FREEZE-14 结束后供 Fable 和用户裁决的提案。

## 1. 边界与审计记录

- 遵守 `CLAUDE.md` 第 9 条 FREEZE-14。冻结期内 H16 只能采集、回放和记提案。
- 本轮没有读取或修改 `D:\kalshi-secrets`，没有调用交易入口，没有运行 `tests/`，没有重启或停止进程。
- 所有 SQLite 连接都使用 `file:...?mode=ro`。读取范围为 `D:\kalshi-ticks\ticks_*.db` 与 `data\*shadow*.db`。
- `build_shared.txt` 在工作区不存在；本设计采用用户消息中的共享铁律、`CLAUDE.md` 第 9 条、`research/GAP245_ARCHITECTURE.md`、`research/SHORTCYCLE_DESIGN.md`、B2 原始报告/脚本与 `strat_c1.md`。
- 工作区已有与本任务无关的未提交改动。本轮只新增本文，没有覆盖它们。

## 2. B2 同口径延长复算

### 2.1 固定口径

复算没有重新选参数。H16 固定为 `z >= 0.8, L = 0.86`，固定比较组为 `L = 0.84`。

独立样本是一个 15m `ticker` 窗口。T0 是热门侧 quote mid 第一次进入 `[0.84, 0.94]` 的时刻。YES 热门持有侧报价取 `yes_bid`；NO 热门取 `1 - yes_ask`。B2 的 1c-through 保守代理定义为：86c 假想买单只有在持有侧 bid 到达 85c 或更低时才算“触及”；84c 比较组要求 bid 到达 83c 或更低。

每张一合约、maker fee 暂记 0 时：

```text
EV/成交 = win_rate - L
EV/窗口 = P(1c-through) * (win_rate_given_through - L)
```

本式是 B2 的 quote-path proxy，不是 queue-aware fill。bid 下穿可能由撤单造成；没有逐笔成交量和队列前量时，它不能证明我们的订单成交。

### 2.2 数据与可复现限制

- tick 分区：`ticks_20260705.db` 至 `ticks_20260710.db`。本轮只扫描四个 15m series 的索引范围，共发现每币 430 个 ticker，读取 1,220,321 条 quote 行。
- spot/z：复用 B2 已缓存 Coinbase 5m 数据，并拼接 scratchpad 中已存在的 `candles_5m_5d.json`；本轮没有联网。BTC/ETH/SOL 可延长至 07-09 21:45Z，XRP 没有同期增量。
- 15m reference 仍沿用 B2 的“窗口开始前 Coinbase 5m close”近似；它不是官方 settlement oracle。
- tick 表没有 result。复算沿用 B2 的终盘 0/1 附近 quote 推断。交叉核对 `h10_shadow.db` 的已结算 BTC/ETH/SOL 子集时，579 个结果中 551 个可由终盘 quote 推断，且 551/551 与 shadow result 一致；其余 28 个不可推断。该子集没有 XRP，且受 h10 选样影响，不能替代 H16 的完整官方结算分母。

因此下表只能回答“B2 的旧形状在更多 quote 上是否漂移”，不能回答“可真实成交的 H16 是否赚钱”。

### 2.3 固定 86c 结果

`触及` 指 bid 到 86c；`through` 指 B2 的 1c-through（bid 到 85c）。Wilson 列是 `win|触及` 的 95% Wilson 下界减 0.86，单位为每成交合约美元。

| 币 | z 合格窗 n | 触及 n | through n | win\|触及 | win\|through | EV/窗 @86 | EV/窗 @84 | Δ(86-84) | safe n / 胜率 | crossed n | Wilson EV/成交下界 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 146 | 137 | 133 | 94.16% | 93.98% | +7.27c | +5.59c | **+1.68c** | 137 / 94.16% | 0 | **+2.90c** |
| ETH | 145 | 137 | 133 | 94.89% | 94.74% | +8.01c | +6.87c | **+1.14c** | 137 / 94.89% | 0 | **+3.83c** |
| SOL | 139 | 133 | 128 | 94.74% | 94.53% | +7.86c | **+8.32c** | **-0.46c** | 133 / 94.74% | 0 | **+3.53c** |
| XRP | 32 | 30 | 29 | 93.33% | 93.10% | +6.44c | +3.25c | +3.19c | 30 / 93.33% | 0 | **-7.32c** |

固定 86c 的 proxy EV 在四币样本中均为正，BTC/ETH/SOL 的新增 cohort 也为正。结论仍受五个 UTC 日块、终盘推断、非官方 reference 和非 queue fill 限制。网格诊断把 BTC/ETH 的 L* 留在 86c，却把 SOL 的 L* 移到 84c；FREEZE-14 禁止据此改任何参数。

### 2.4 预注册门逐项裁决

| 预注册判据 | 当前观测 | 裁决 |
|---|---|---|
| 每币 n >= 80 个 z 合格已结算窗口，触及 >= 20 | proxy：BTC 146/137、ETH 145/137、SOL 139/133、XRP 32/30；tick 表本身的官方 result 为 0 | **FAIL**：XRP 窗口不足；完整官方结算分母未建立 |
| EV/窗(86) 比 @84 至少 +1.0c | BTC +1.68c；ETH +1.14c；SOL -0.46c；XRP +3.19c（旧短样本） | **FAIL**：SOL 明确不满足 |
| win\|safe touch >= 92% | 四币点估计 93.33%–94.89% | 点估计 PASS，但不是完整 GO |
| win\|crossed 显著低于 safe | 四币 crossed 均为 0 | **不可检验**，不能把 0 样本写成“安全” |
| Wilson 下界 EV/成交 > 0 | BTC/ETH/SOL 为正；XRP -7.32c | **FAIL**：XRP 不满足 |
| queue-aware、hold-to-settle、净费用 P&L | 当前 tick 缺逐笔 size/taker side/官方 result；B2 只有 through proxy | **未实现** |

**数据席结论：**“86c 可能捕获震荡折扣”的结构假说没有被三币 proxy 杀死；“H16 固定 86c 已达到可晋升门”被当前数据否定。状态应保持 `HOLD_SHADOW`，不得写入变更提案为 84→86，更不得接实盘路径。

## 3. 生产影子到最小真实执行探针

### 3.1 证据阶梯

| 等级 | 数据/动作 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| D0 demo | `KalshiLive(demo=True)` 的挂/撤/部分成交/对账 | OMS 机制和错误处理 | 生产 edge、生产 fill rate、生产 P&L |
| S1 production quote shadow | 生产 quote、固定 T0、固定 86c、无订单 | 信号频率、quote path、数据完整性 | maker 成交 |
| S2 queue-confirmed shadow | 完整 level、trade size/taker side、queue ahead | 保守可归因 shadow fill | 真实账户延迟和交易所个体队列位置 |
| P1 最小真实执行探针 | 用户逐次授权的最小合约数、独立 title | shadow/live fill 偏差、真实 fee/partial fill | 策略显著盈利 |
| P2 settled reconciliation | 交易所 fill + 官方 settlement + 现金流水 | 单探针真实净 P&L | 放大仓位或改门的授权 |

FREEZE-14 期间只允许 S1/S2。P1/P2 的代码接线、下单和金额决策都不属于本施工波。

### 3.2 queue-aware fill 规则

影子订单在 `arrival_ts = decision_ts + frozen_latency` 才进入队列。`frozen_latency` 必须来自一次预注册的测量清单，不能按结果挑值。

1. 将 YES/NO 统一为“持有侧 bid”。NO 86c 对应 YES ask 14c；所有深度和成交都先标准化到持有侧。
2. 在 arrival snapshot 读取 86c 档位的 `queue_ahead`. 若目标价不在完整 book 中，返回 `UNOBSERVABLE`，不能把缺档当作零队列。
3. arrival 时若目标单会立即跨 ask，它不再是 maker。记录 `REJECT_MARKETABLE`，不得按 maker P&L 计入。
4. 订单生效后，目标价新增量排在我们的单后；不增加 `queue_ahead`。撤单量不保守地减少 `queue_ahead`，因为无法知道撤的是队首还是队尾。
5. 同价、正确 taker side 的累计成交量先消耗 `queue_ahead`，余量才填我们的影子单。持有侧成交价严格穿过 86c 时，可把仍在场的 86c 单判为已穿价成交。
6. partial/fractional fill 原样记录，不做 `int(fill_count)`。单窗口多条 child fill 合并为一个 intent，避免扩 n。
7. seq gap、snapshot 重建、时钟倒退、目标档深度缺失或 trade channel 缺失时，fill 状态为 `UNOBSERVABLE`。quote bid 下穿只允许标记 `UPPER_BOUND_TOUCH`，不允许标记成交。

当前 `ticks_*.db` 只保存 top-3 quote snapshot 和 `last_trade_px`，没有 trade size/taker side，也常看不到 86c 档位。因此当前数据最多产生 S1 和 fill 上界，不能产生 S2。

### 3.3 隔离 demo、错误成交和波段管理

- 每条记录强制 `venue = demo | production` 与 `execution_mode = quote_proxy | queue_shadow | live_probe`。任何跨类别聚合直接报错。
- primary outcome 固定为 hold-to-settle。S1/S2 shadow fill 或 P1 live fill 一旦发生，不运行止盈、止损、波段换手或 LLM 复评；这些反事实只能列在 secondary 表。
- primary P&L 使用官方 result、实际/影子 fill 价、series 级真实 fee 与小数合约数：`net_pnl = payout - cost - fee`。
- 主指标是 intent-to-treat `net P&L / eligible window`：未成交窗口记 0。`P&L / fill`、fill ratio、30s/5m markout 是次指标，不能用 fill-conditioned 盈利掩盖低 fill rate。
- 同一 ticker/side/config hash 只允许一个 intent。按 UTC 日 block bootstrap；币和 regime 预先分层，只报告，不在冻结期调门。
- demo P&L 永远是 D 类；quote proxy 永远不能升级为 live fill；P1 的一张/最小张探针也只校准摩擦，不提供统计显著性。

### 3.4 P1 提案的硬前置

只有以下条件全部满足，Fable 才可在边界日后向用户提出 P1；本文不代用户批准：

1. H16 的冻结预注册门用官方 settlement 和完整 spot/reference 重跑通过；
2. S2 能给出 queue-confirmed fill，且参数 manifest 在观察窗前冻结；
3. demo OMS 冒烟通过，确认 partial fill、取消竞速、独立 title 和对账；
4. Fable 完成代码终审，用户明确授权合约数/美元帽；
5. 探针使用独立 `H16_EXEC_PROBE_V1` title，成交后持有到结算，不并入 h15/h10/favorites；
6. 任何扩大金额、恢复预算、加杠杆或修改验收仍由用户决定。

## 4. tickstore 消费层设计

### 4.1 现状与蓝图差异

| 项目 | 当前 `ticks_*.db` | GAP245 蓝图/重审所需 | 影响 |
|---|---|---|---|
| 时间 | `ts TEXT` | `ts_ms INTEGER`、统一 UTC | 跨分区和 dwell 要解析字符串 |
| 唯一性 | 无主键；索引 `(ticker, ts)` | `(ticker, ts_ms, seq)` | 重放必须显式去重 |
| book | top-1 + `l2_json`/`l3_json` | 可验证的完整目标档/前 3 档 | 86c 不在 top-3 时 queue 不可见 |
| seq | 每秒 snapshot 携带 subscription seq；相邻值可大跳 | snapshot boundary、gap/rebuild validity | 不能用 `seq+1` 判断当前库连续 |
| trade | 只有 `last_trade_px` | 独立 trades：time、price、size、taker side | 不能做 queue-confirmed fill |
| settlement | 无 | 官方 result/source/revision | 只能终盘推断 |
| 存储 | 完整日约 14GB | 事件驱动目标 <1GB/日 | 消费查询必须限 ticker/时间窗 |

### 4.2 `src/tickstore.py` 规格（新模块，不接交易路径）

模块只提供 read-only 访问和数据质量语义，不导入 `pipeline`、`live` 或下单 client。

```python
@dataclass(frozen=True)
class BookLevel:
    price_c: int
    size_fp: Decimal

@dataclass(frozen=True)
class Book:
    ticker: str
    ts_ms: int
    seq: int | None
    yes_bid_c: int | None
    yes_ask_c: int | None
    bid_levels: tuple[BookLevel, ...]
    ask_levels: tuple[BookLevel, ...]
    source_db: Path
    complete: bool
    quality_flags: frozenset[str]

class TickStore:
    def latest_book(self, ticker: str, *, max_age_ms: int | None = None) -> Book | None: ...
    def book_at(self, ticker: str, ts_ms: int, *, max_age_ms: int) -> Book | None: ...
    def iter_books(self, ticker: str, start_ms: int, end_ms: int) -> Iterator[Book]: ...
    def dwell_ms(self, ticker: str, predicate, *, end_ms: int, max_gap_ms: int) -> DwellResult: ...
    def capabilities(self) -> TickCapabilities: ...
```

实现约束：

- 每个连接使用 URI `mode=ro` 和 `PRAGMA query_only=ON`；active WAL 分区禁止 `immutable=1`，否则会漏 WAL。
- 分区按 UTC 时间解析，不按机器本地日期猜。跨午夜查询最多打开需要的两个/三个日库。
- schema detection 同时识别当前 v1 与未来 v2。未知列型、坏 JSON、重复 `(ticker, ts, seq)` 都 fail closed。
- v1 的 `seq` 只能作 provenance，不能假定逐行连续。`dwell_ms` 用 timestamp continuity，并返回 `complete/max_gap_ms/observed_rows`；不完整 dwell 不过门。
- `depth_at(price)` 找不到目标价时返回 `UNOBSERVED`，不能返回 size 0。
- 价格统一转整数 cents；当前 0.001 报价若不能无损映射到 cents，保留 milli-cents provenance，并禁止进入 1c H16 fill 判定，直到 Fable 冻结取整规则。
- 查询必须带 ticker 与有界时间，禁止全表 `ORDER BY`。只读层不创建索引、不 VACUUM、不改 WAL。

### 4.3 H16 独立 sidecar

建议新增 `src/h16_shadow.py` 与 `scripts/h16_shadow_once.py`，写入全新的 `data/h16_shadow.db`。它们不得被 `pipeline.py` import，也不得持有任何下单函数引用。

最小表：

- `manifests(experiment_id, created_ts, git_commit, config_json, config_sha256, data_schema, freeze_id, research_only)`；
- `intents(intent_id, event_key UNIQUE, ticker, asset, side, decision_ts, arrival_ts, close_ts, L_c, z, spot, reference, regime, source_seq, data_quality, reject_reason)`；
- `queue_observations(intent_id, ts, queue_ahead_fp, trade_fp, fill_lb_fp, fill_ub_fp, status, quality_flags)`；
- `settlements(event_key UNIQUE, result, official_source, settled_ts, observed_ts, revision, raw_sha256)`；
- `outcomes(intent_id UNIQUE, fill_class, fill_fp, avg_px_c, fee_usd, gross_pnl_usd, net_pnl_usd, reconciled)`。

`event_key` 至少含 ticker、side 与 frozen config hash。settlement 未到时保持 `PENDING`；禁止用最后 quote 自动回填 official result。研究报告只消费 `reconciled=1` 或明确标记的 proxy 分区。

### 4.4 trade/queue 数据缺口的施工边界

`src/tickstore.py` 能立刻支持 quote 门重审，却不能从现有 top-3 snapshot 发明完整 queue。S2 需要未来的独立、只采行情的 WS 观察器保存 snapshot/delta/trade。该观察器必须是新进程/新模块，先由 Fable 审核；不得修改或重启当前 `D:\kalshi-ticks\ws_capture.py`。在观察器获批前，H16 recorder 必须把 fill 标成 `QUOTE_PROXY_ONLY`。

## 5. 给 Opus/Sonnet 的实现规格

### Wave A：Opus — read-only tickstore

交付：`src/tickstore.py` 与一个不在 `tests/` 下的 `scripts/tickstore_smoke.py`。

验收：能跨 UTC 分区读取同一 ticker；v1/v2 schema detection；Decimal/整数价格规范化；坏 JSON、陈旧 quote、缺档、时间 gap 均 fail closed；对当前库只发有界索引查询；没有任何写 DB 或交易 import。

### Wave B：Sonnet — H16 quote shadow/replay

交付：`src/h16_shadow.py`、`scripts/h16_shadow_once.py`、`scripts/h16_replay.py`。默认模式必须是 `--shadow --no-order`；代码中不得出现 `place_limit`、`place_exit` 或 production order endpoint。

验收：固定 `z>=0.8/L=86c/@84` manifest；一个 ticker 只记一个 intent；输出 proxy 与 official/queue-confirmed 分区；官方 settlement 未到不结算；primary hold-to-settle；报告固定包含 n、touch、through、queue fill、fill ratio、ITT P&L/window、P&L/fill、fee、day-block CI、safe/crossed 和数据缺口。

### Wave C：Opus 红队 + Fable 终审

红队必须尝试证明：quote 下穿被误记成交、NO 侧价格翻转错误、跨日重复计数、h10 结果选择性 join、陈旧 spot 继续算 z、最后 quote 冒充官方 result、demo/live 混表、partial fill 被取整、波段退出污染 primary P&L。

Fable 终审前不 wire。终审只能批准影子/基建；任何实盘接线、probe 合约数或美元帽仍需用户另行授权，并受 FREEZE-14 边界日约束。

### 明确不碰实盘路径

| 项目 | 本施工波动作 | 对实盘交易路径影响 |
|---|---|---|
| `src/tickstore.py` | 新增只读库 | 无；不被 pipeline import |
| `src/h16_shadow.py` | 新增纯研究模块 | 无；不含 order client |
| `scripts/h16_shadow_once.py` / replay | 新增独立 CLI | 无；默认 no-order |
| `data/h16_shadow.db` | 新 sidecar | 无；独立 ledger/title |
| `src/pipeline.py` / `src/live.py` / `config.yaml` | **不修改** | 实盘门与参数保持冻结 |
| quant_loop / ws_capture / watchdog | **不重启、不修改** | 运行状态不变 |

## 6. 施工验收命令（供实现波使用，本轮未执行）

不得运行 `tests/`。实现波只允许：

```powershell
python -m py_compile src/tickstore.py src/h16_shadow.py scripts/h16_shadow_once.py scripts/h16_replay.py
python scripts/tickstore_smoke.py --db "D:\kalshi-ticks\ticks_20260708.db" --read-only
python scripts/h16_replay.py --shadow --no-order --db-glob "D:\kalshi-ticks\ticks_*.db"
python scripts/h16_shadow_once.py --demo --smoke --no-production --no-order
```

demo smoke 必须硬断言 `KalshiLive(demo=True)`、demo base URL 与 `venue=demo`，且结果永不进入 edge 门。若 demo 无 crypto ticker，只验证读取、记录和隔离机制；不得用其他 demo 市场的 P&L 替代 H16 证据。

## 7. 待 Fable 定案

1. 冻结文本“每币×家族”是否只指 H16 的 15m 家族；本报告按 H16/h15 上下文只复算 15m，不擅自扩到 hourly。
2. `z` 的正式 oracle/reference。B2 的 Coinbase 5m 近似只适合 proxy；晋升门应记录合约规则指定的 settlement source 与可审计 start reference。
3. milli-cent quote 到整数 cent 的取整法。取整会改变 1c-through 与 queue 档位，必须在新观察窗前冻结。
4. 是否批准一个独立行情观察器补 full book/trades。批准前 S2 永远保持 `UNOBSERVABLE`。
5. P1 只在 FREEZE-14 边界裁决、Fable 终审和用户金额授权后另立提案；本文不包含启用开关。

{"seat":"D3-CODEX-DESIGN-DATA","status":"HOLD_NO_PROMOTION","freeze14_compliant":true,"scope":"shadow_and_infrastructure_only","as_of_utc":"2026-07-10T04:40:06Z","deliverable":"build_d3_design.md","h16":{"fixed":{"z_floor":0.8,"L":0.86,"comparator_L":0.84},"proxy_counts":{"BTC":{"windows":146,"touches":137},"ETH":{"windows":145,"touches":137},"SOL":{"windows":139,"touches":133},"XRP":{"windows":32,"touches":30}},"delta_ev_window_c":{"BTC":1.68,"ETH":1.14,"SOL":-0.46,"XRP":3.19},"official_complete_denominator":false,"crossed_samples":0,"verdict":"proxy_shape_survives_but_preregistered_gate_fails"},"implementation":{"new_only":["src/tickstore.py","src/h16_shadow.py","scripts/h16_shadow_once.py","scripts/h16_replay.py","data/h16_shadow.db"],"wire_to_pipeline":false,"real_order_code":false},"review":{"codex_design_data":"complete","opus_red_team":"pending","fable_final":"pending","user_money_authorization":"required_for_any_future_probe"}}
