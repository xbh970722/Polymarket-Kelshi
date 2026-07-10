# W3 天气条件尾部影子组施工规格

状态：WX-DIRECTOR 定稿，供 Opus + Sonnet 施工  
版本：`W3_NWS_TAIL_MAKER_V1` / `W3_GATE_V1`  
裁决时间：2026-07-10  
授权范围：只实现采集、训练、影子 intent、反事实 fill、结算、报告和裁决；不接实盘，不接现有调度。

## 0. 一页施工令

新增独立模块 `src/wxtail.py`。不要扩写 `src/wxfade.py`，也不要把新逻辑塞进 `src/weather.py`。W1、W2 是被观察对象，不是 W3 的代码宿主。

本批只允许新增以下文件；若施工需要改变清单，先停在 review，不要自行扩大范围：

- `src/wxtail.py`
- `scripts/wxtail_shadow.py`：薄 CLI 包装
- `scripts/wxtail_smoke.py`：fixture/临时库 smoke，不进入 `tests/`
- `config/wxtail_shadow.yaml`
- `fixtures/wxtail/*`：去敏、确定性公开样本

本批不得修改：

- `src/weather.py`、`src/wxfade.py`、`src/pipeline.py`、`scripts/quant_loop.py`
- 现有 `config.yaml`、任何 live 风险门、尺寸、预算或调度
- `data/ledger.db`、`data/weather_cal.db`、`data/wxfade_shadow.db`

默认新库为 `data/wxtail_shadow.db`。正式 smoke 必须用临时路径，不得借 smoke 污染默认库。模块不得 import `KalshiLive`，不得读取账户、凭据或 `D:\kalshi-secrets`，不得存在下单函数。CLI 只提供 `collect`、`freeze-model`、`scan`、`refresh`、`settle`、`report`、`adjudicate`；遇到 `--live` 必须非零退出。

即使 `adjudicate` 返回通过，也只能生成上线提案。代码不得自动 wire、自动下单、提高美元上限、恢复预算或改变验收门。

## 1. 输入审计与最终裁决

用户点名的 `build_d2_spec.md`、`build_d2_discussion.md`、`build_d2_review.md` 不在当前工作树、Git 历史或已登记 worktree 中。当前仓库只有合并稿 `build_d2_design.md`；该稿包含设计、施工规格、review 和第二轮回应。本规格以合并稿第 9 节的修订覆盖前文冲突项。

共识方向正确：独立新模块、阶段 A 训练与阶段 B 冻结前向、站点级概率、模型条件入组、maker 影子成交证明、预注册门和禁止自动实盘。原稿仍有七个必须在施工前闭合的缺口：

1. 2026 Kalshi API 已提供 `strike_type`、`floor_strike`、`cap_strike`。它们必须是 payout 集合的主语义；subtitle、rules 和 ticker 只做交叉核验。
2. 价格网格由每个市场的 `price_ranges` 决定，尾部可能使用亚分 tick。禁止用 float 或硬编码 1c。
3. NWS CLI 气候日是午夜到午夜 Local Standard Time；夏令时期间相当于民用时间 01:00 到次日 01:00。不得复用 `weather.py` 的 civil-midnight 窗口。
4. NWS 公布的是观测与确定性逐时预报，不直接提供所需的“命中概率”。`q_met` 必须来自只用扫描时已发布 NWS 信息训练出的站点残差分布。
5. 原建议 schema 无法无损保存逐笔成交、规则修订和结算修订；本规格改成 append-only 证据表。
6. “每城市日一单”与三个 tau 层的最低样本数存在抢占冲突。本规格用确定性城市日分层分派，避免 20–48h intent 永久吃掉 2–8h 样本。
7. W2 只有 `print != fill` 证据，不能与 W3 的 F2 成交证明形成同证据等级的硬晋升门。W2 必须同期报告，但 V1 的主门只有净 P&L 与 paired Brier 两个 CI。

## 2. 诚实核：尾部现在是否仍赚钱

### 2.1 Kalshi 本地数据

只读重算 `data/backfill_weather.db`。口径是：在 `2 < tau <= 48h` 内，每 ticker 取第一次落入 `[1c,15c)` 的公开成交 print，乐观地假设以该 print 买 1 张 YES、持有到结算并扣通用 taker 费。该口径不是 maker fill，必须标注 `print != fill`。

| 样本 | n | 城市日 | 结算日 | YES 命中 | 平均入价 | 净 P&L | 均值 | 结算日 block 95% CI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-04-29 至 2026-07-04 | 2,407 | 469 | 67 | 63 | 7.66c | -$145.47 | -6.04c | [-6.69c, -5.39c] |
| 2026-06-20 起 | 483 | 98 | 14 | 13 | 7.55c | -$28.31 | -5.86c | [-7.02c, -4.57c] |

四个价格子带的点估计全为负。只有 `(2,8]h` 子层接近持平：`n=92`、均值 `+0.35c`、95% CI `[-4.49c,+7.80c]`。这足以否决“纯 `<15c` 价格阈值当前在 Kalshi 普遍正 EV”，但不能否决尚未记录的 NWS 条件 maker 子集。

### 2.2 gopfan2 外部核实

截至 2026-07-10 09:30 UTC，Polymarket 官方天气 leaderboard API 对 gopfan2 钱包显示：all-time `+$354,222.96`、成交量 `$4,607,415.41`；近 1 日 `+$88.81` 且成交量为 0；近 1 周 `-$3,435.84`；近 1 月 `-$1,881.60`。这是钱包/类别聚合，可能含持仓 mark，也不能归因到“低于 15c + 天气模型”这一条规则。

官方入口：

- [Polymarket 天气总榜](https://polymarket.com/leaderboard/weather/all/profit)
- [Polymarket leaderboard API（gopfan2，天气）](https://data-api.polymarket.com/v1/leaderboard?category=WEATHER&timePeriod=MONTH&orderBy=PNL&limit=1&offset=0&user=0xf2f6af4f27ec2dcf4072095ab804016e14cd5817)

最终判定分两层：

- 纯价格尾部：`no`，现有 Kalshi print 诊断显著为负。
- `NWS 条件概率 + maker` 尾部：`unknown`，尚无可归因、可成交的冻结前向样本。

所以本批目标是“影子门先证伪”，不是把外部历史赢家复制到真钱。

## 3. 模块边界与强制 API

`src/wxtail.py` 可以复用：

- `src.weather.CITIES` 的 series/station/坐标/时区作为启动快照；每个 event 仍须重新核验规则和 settlement source。
- `KalshiPublic` 的公开 GET 能力。
- 经 fixture 验证后的通用 fee 公式。

不得复用：

- `weather.candidates()`：它把采集、报价门和旧概率模型耦合在一起，且使用 civil-midnight。
- `wxfade.scan()` 或其写库路径。
- `weather._bucket_prob()` 作为 T-high 真值。W3 只按结构化 strike 构造 payout 集合。

最低 API：

```python
@dataclass(frozen=True)
class TailOpportunity:
    opportunity_id: str
    strategy_version: str
    ticker: str
    event_ticker: str
    series: str
    station: str
    settlement_local_date: str
    decision_layer: str
    decision_ts_utc: str
    tau_h: float
    q_met: float
    q_met_lcb: float
    q_trade: float
    q_trade_lcb: float
    yes_bid_units: int
    yes_ask_units: int
    maker_limit_units: int
    contracts: int
    fee_reserve_units: int
    storm_flag: bool
    storm_group_keys: tuple[str, ...]

def collect_shadow(cfg, *, now=None, db_path=None,
                   market_source=None, nws_source=None) -> "CollectReport": ...

def freeze_model(cfg, *, db_path=None, output_path=None) -> "FreezeReport": ...

def scan_shadow(cfg, *, now=None, db_path=None, model_manifest=None,
                market_source=None, nws_source=None) -> "ScanReport": ...

def refresh_shadow(cfg, *, now=None, db_path=None,
                   market_source=None, nws_source=None) -> "RefreshReport": ...

def settle_shadow(*, now=None, db_path=None,
                  market_source=None, cli_source=None) -> "SettleReport": ...

def report_shadow(*, db_path=None, wxfade_db=None) -> "TailReport": ...

def adjudicate_shadow(*, db_path=None, wxfade_db=None,
                      gate_version="W3_GATE_V1") -> "GateReport": ...
```

所有外部源必须可注入。fixture 路径不得发网络请求。默认实现只准公开 GET。

## 4. 时间、站点与规则语义

### 4.1 精确结算对象

随机变量是 Kalshi 对该 event 使用的 NWS Daily Climate Report 整数最高温 `H_cli`，不是手机天气、point forecast 的最高温，也不是简单的 METAR 小时观测最大值。

每个 event 保存并核验：

- series settlement source URL、contract terms URL 与内容 hash
- `event_ticker`、series、station ICAO、CLI `issuedby`
- `rules_primary`、`rules_secondary`、subtitle 及 hash
- `strike_type`、`floor_strike`、`cap_strike`
- `settlement_local_date` 和固定 LST UTC 窗口

任一字段缺失、冲突或发生未审规则修订时，记录 `ineligible_rules`，不猜默认值。

### 4.2 LST 气候日

每城配置独立的 standard UTC offset。气候窗口固定为：

```text
[settlement_date 00:00 LST, next_date 00:00 LST)
```

在 DST 季节，该窗口对应当地民用时间 01:00 至次日 01:00。模型同时保存 `lst_hour` 与 `civil_hour`，但窗口裁切只用 LST。官方依据是 NWS CLI 的 midnight-to-midnight Local Standard Time 定义；参见 [NWS Instruction 10-1004](https://www.weather.gov/media/directives/010_pdfs/pd01010004curr.pdf)。

### 4.3 payout 集合

以结构化字段为主；字段契约见 [Kalshi Get Market](https://docs.kalshi.com/api-reference/market/get-market)：

```text
strike_type == greater: H_cli > floor_strike
strike_type == less:    H_cli < cap_strike
strike_type == between: floor_strike <= H_cli <= cap_strike
```

只接受这三类。subtitle、rules 与 ticker 必须给出同一整数集合。例：`KXHIGHNY-26JUL10-T94` 的 YES 是 `H_cli >= 95`，不是 `H_cli >= 94`。

同一 event 的所有市场区间必须在整数轴上无重叠、无缺口地覆盖 `(-inf,+inf)`。不满足时整场 event 禁止入组。完整 event 的概率和容差为 `1e-12`；不要逐桶加 floor。

## 5. 原始采集：先于所有策略门

`collect_shadow` 每次运行都采集 7 个配置 series 的全部 active event/market，不受价格带、模型 edge、家庭帽、账户、仓位或是否已有 intent 影响。无双边报价也要记录 market metadata 和 `quote_state`；只有正式 eligibility 要求双边正尺寸。

每份外部响应保存：source URL、请求参数、request/received UTC、HTTP ETag/Last-Modified（如有）、原始内容压缩体、sha256 和解析版本。决策 run 先取 NWS，再取 Kalshi market/quote；最后一份必需 quote 收到后立即冻结 `decision_ts_utc`，并用它计算 tau 和资格。至少包括：

- Kalshi series、markets、market、public trades、fee changes
- NWS station observations
- NWS point/hourly forecast，含 `generatedAt`、`updateTime` 和逐时 valid interval
- NWS alerts 原文
- 结算后的 Kalshi result/expiration value 与 NWS CLI 文本

模型信息集只能引用 `source_received_ts <= decision_ts_utc` 的 artifact。观测本身 timestamp 晚于 decision time 时不得使用。forecast period 进入“剩余路径”必须与 LST 窗口相交且 period end 晚于 decision time。保存每条 source age；正式资格还要求最后 market quote 距 decision time 不超过 30 秒，超时记 `ineligible_stale_quote`。不得把 run 启动时间误作信息截止时刻。

采集失败写 run/error 状态；不得让 W3 异常传播到现有 live pipeline。

## 6. 阶段 A：概率模型训练与冻结

阶段 A 不产生正式胜负。至少积累 60 个 settled city-days、每城至少 6 个；所有 tau 层均须有 snapshot。达不到只可 `ACCUMULATE_STAGE_A`。

目标值是最终 `H_cli`。信息只含扫描时已发布的：已观测最高温、观测质量标记、剩余逐时 forecast path、station、LST hour、lead/tau、season、forecast revision 和 storm regime。

预注册四个模型族：

- M0：现行 mu/sigma 的高斯对照，但使用正确 strike、LST 和 event 归一化；不复制 T-high bug或逐桶 2.5% floor。
- M1：`station x lead` 偏差修正；偏差夹在 `±3F`，sigma 地板 `1.2F`，小样本向全局 shrink。
- M2：`station x lead_band x lst_hour_band x season x storm` 分层经验残差；样本不足依次向 station、气候区、全局 shrink。
- M3：M1 中心加固定 `nu=4` 的 Student-t 尾。

用逐日 rolling-origin OOF 选择，city-day 是不可拆分单元。CRPS 为主指标，log loss 为副指标；并列时选更简单的模型。独立 city-days 少于 100 时，M2 必须在预注册排序上同时胜过 M1、M3 才能入选。

输出三条概率：

- `q_raw`：所选气象分布直接积分。
- `q_met`：只用训练期 OOF 映射得到的气象校准概率。
- `q_trade`：把 `q_met` 与同 snapshot 市场 mid 在 log-odds 上 shrink。

冻结 shrink 规则：

```text
logit(q_trade) = w * logit(q_met) + (1-w) * logit(mid_yes)
```

`w` 只在阶段 A 的 OOF 结果上从固定网格 `{0.0,0.1,...,1.0}` 选择，以 log loss 最小为准；并列取较小 `w`。tau 层 OOF 样本不足 100 时用全局 `w`。logit 输入 clip 到 `[1e-6,1-1e-6]`。

`q_met_lcb` 与 `q_trade_lcb` 分别是冻结训练 city-day block bootstrap 后对应概率的第 10 百分位：2,000 次、固定 RNG seed、同一批 bootstrap residual/model 参数在阶段 B 不更新。它们只是保守入组信号，不宣称频率学覆盖率。

模型 manifest 至少冻结：训练截止 UTC、数据 hash、schema/parser/regime 版本、CITIES/standard-offset 快照、规则 hash 集、候选族与排序、参数、`w`、bootstrap seed/索引、代码 hash、fee 规则 hash、strategy/gate 版本和全部门槛。阶段 B 从 manifest 被 reviewer 接受后的下一次完整扫描归零开始。

任何会改变 q、候选、limit、fill、settlement 或 gate population 的修复都升 strategy/model 版本并重启正式计数。纯展示修复可保留计数，但要写 migration audit。

## 7. 阶段 B：候选、分层与 maker intent

### 7.1 候选与 eligibility

所有条件同时满足：

1. 规则、station、LST 窗口和 event partition 全部通过。
2. `2 < tau_h <= 48`，分为 `(2,8]`、`(8,20]`、`(20,48]`。
3. 正尺寸双边 YES book 存在，`0 < yes_bid < yes_ask < 1`。
4. `0.01 <= mid_yes < 0.15`。`[0,0.01)` 只记录为诊断，不进入 V1。
5. forecast 与 observation legs 通过冻结完整性规则。
6. 冻结 shrink 权重 `w > 0`，且 `q_met_lcb > mid_yes`；这条保证入组确实由独立 NWS 信号条件化，宽 spread 或纯价格阈值不能单独触发。
7. 可构造合法 maker price/size，且 `q_trade_lcb / maker_limit >= 1.50`。
8. `q_trade_lcb - maker_limit - fee_reserve_per_contract >= 0.05`。

第一次满足 1–5 的 snapshot 建立 price candidate；第一次满足全部 1–8 的 snapshot 建立 formal opportunity。重复扫描不增加 n。

### 7.2 tau 分层分派

每个 `(strategy_version, series, settlement_local_date)` 只能属于一个决策层：

```text
decision_layer = sha256(frozen_salt | strategy_version | series | settlement_local_date) mod 3
```

三个余数依次映射到 `(2,8]`、`(8,20]`、`(20,48]`。salt 写入 manifest。非分派层仍完整采集、评分和进入概率诊断，但不得创建 V1 intent。

在分派层内，若该城市日尚无 intent，则从同一次 run 的 eligible ticker 中选 `q_trade_lcb - all_in_limit` 最大者；并列依次按更低 maker limit、ticker 字典序裁决。intent 一旦创建就拥有该城市日，后续更高 edge 只能记 `eligible_not_selected_cityday_owned`。这是在线规则，不得结算后回看“当天最好的一只”。

### 7.3 动态 price grid 与 fee

价格以固定点整数保存，内部单位为 `1e-6` 美元。只从 market `price_ranges` 推导合法价和 next tick；禁止 binary float 比较，也禁止按 `price_level_structure` 名字硬编码。API 迁移依据见 [Kalshi Fixed-Point Migration](https://docs.kalshi.com/getting_started/fixed_point_migration)。

对每个 candidate 枚举合法 maker limit `L`：

- `yes_bid <= L < yes_ask`
- `L <= 0.14`
- `L` 不高于 `yes_bid` 的下一个合法 tick
- 若 `L == yes_bid`，视为 join；高一 tick 视为 improve

费用必须从当时 series `fee_type`、`fee_multiplier`、fee change 和官方 schedule snapshot 复算；字段来源见 [Kalshi Get Series](https://docs.kalshi.com/api-reference/market/get-series)。未知费用时 fail closed 为 `ineligible_fee_unknown`。V1 主 P&L 的 `fee_reserve` 取适用 maker fee与同价格/张数 taker fee中的较大者；另报官方 maker-fee sensitivity，不得用低费场景晋升。

只使用整数张。对每个 `(L,C)` 计算：

```text
max_loss = C * L + conservative_fee(L, C)
max_loss <= $1.00
q_trade_lcb - L - conservative_fee(L,C)/C >= 0.05
q_trade_lcb / L >= 1.50
```

先取满足条件的最高 `L`，再取不超过 `$1` 风险单位的最大 `C`。无合法组合记 `eligible_unpostable`，不创建 intent。

intent 截止取以下最早者：创建后 6 小时、下一次 NWS forecast revision、`tau=2h`。refresh 首次看到 `q_trade_lcb` 跌破 all-in break-even 时取消。一个 strategy version/ticker 最多一个 formal intent；取消后不重发。

## 8. maker 影子成交证明

这是一组反事实订单，绝不提交交易所。

| 级别 | 证据 | 主 P&L |
|---|---|---|
| F0 | 仅创建假想 maker intent | 否 |
| F1 | ask/print 只触及 limit，或队列证据不足 | 否 |
| F2_print | intent 后、取消/TTL 前出现非 block 公共成交；`taker_outcome_side=no`，且 YES 成交价至少严格穿过 limit 一个当时合法 tick | 是 |
| F2b_book | intent 后、取消/TTL 前，正尺寸 best YES ask 被观察到严格低于 limit | 是 |
| F3_demo | demo 机制成交 | 否；本批无需实现 |

`F2_print` 必须按 `trade_id` 去重，保存 `created_time/ts_ms`、`taker_outcome_side`、`taker_book_side`、YES price、`count_fp`、`is_block_trade` 和首次抓取时间。字段语义见 [Kalshi Get Trades](https://docs.kalshi.com/api-reference/market/get-trades)。block trade 永远不能证明订单簿成交。成交价按更保守的 maker limit 记，不按穿价 print 改善。

同一 intent 同时命中时优先标 `F2_print`。等于 limit 只是 F1；没有可靠 taker 方向的 print 也只是 F1。所有 F0/F1/null 报告必须显示 `print != fill`。

## 9. storm 预注册

`storm_flag_v1=1` 当且仅当扫描时已发布的信息满足至少一项：

1. 覆盖 station point 且与 LST 气候日相交的 NWS alert，其 event type 以 Tornado、Severe Thunderstorm、Flash Flood、Winter Storm、Blizzard 或 Ice Storm 开头。
2. NWS hourly period 文本含 thunderstorm，且同 period `probabilityOfPrecipitation >= 50%`。
3. 任意连续 3 个 hourly forecast 点内 `max(temp)-min(temp) > 6F`。

Heat Advisory/Excessive Heat Warning 单列 `heat_regime`，不计 storm。保存原始 alert id、period、触发条款和 `regime_version`。

storm episode 只用天气元数据构造，不看 outcome/P&L。snapshot 先保存原始 `storm_group_keys`：alert 用原始 alert id；无 alert id 的 proxy storm 用 trigger type + series。adjudicate 在 settled eligible city-days 上做确定性 union-find：共享 alert id 的 city-day 合并；无 alert id 的同 series proxy storm在相邻结算日连续触发时合并。最终 `storm_episode_id` 对规范化成员集做 sha256，并以 append-only assignment 保存。报告另做 calendar-week block sensitivity。

## 10. 数据库契约

新库使用 schema version，至少包含以下逻辑表；列可增加，不得删掉证据链：

```text
schema_meta(key PK, value, updated_ts)
runs(run_id PK, command, started_ts_utc, decision_ts_utc, completed_ts_utc,
     strategy_version, model_hash, code_hash, config_hash, status, error_text)
artifacts(artifact_id PK, source, url, request_json, request_ts,
          received_ts, etag, last_modified, sha256 UNIQUE, codec, raw_blob)
events(event_revision_id PK, event_ticker, series, station,
       settlement_local_date, lst_start_utc, lst_end_utc,
       settlement_source_url, terms_url, terms_hash, rules_hash,
       first_seen_ts, supersedes_id)
market_snapshots(run_id, ticker, event_revision_id, strike_type,
       floor_strike, cap_strike, subtitle, rules_hash,
       yes_bid_units, yes_ask_units, no_bid_units, no_ask_units,
       yes_bid_size_fp, yes_ask_size_fp, last_units, volume_fp,
       price_ranges_json, fee_type, fee_multiplier, tau_h, quote_state,
       PRIMARY KEY(run_id,ticker))
nws_snapshots(run_id, event_revision_id, forecast_artifact_id,
       observations_artifact_id, alerts_artifact_id, forecast_issue_ts,
       forecast_update_ts, obs_max_f, obs_latest_ts,
       forecast_remaining_max_f, lst_hour, civil_hour, season,
       storm_flag, storm_trigger_json, storm_group_keys_json, regime_version,
       PRIMARY KEY(run_id,event_revision_id))
model_scores(run_id, ticker, model_version, q_raw, q_met, q_trade,
       q_met_lcb, q_trade_lcb, event_prob_sum, candidate_state, reason_code,
       PRIMARY KEY(run_id,ticker,model_version))
opportunities(opportunity_id PK, strategy_version, ticker,
       first_candidate_run_id, first_eligible_run_id, decision_layer,
       selection_state, UNIQUE(strategy_version,ticker))
intents(intent_id PK, opportunity_id UNIQUE, created_ts, expires_ts,
       maker_limit_units, contracts, fee_reserve_units, max_loss_units,
       state, cancel_ts, cancel_reason)
trade_prints(trade_id PK, ticker, created_ts, ts_ms, yes_price_units,
       count_fp, taker_outcome_side, taker_book_side, is_block_trade,
       first_seen_run_id)
quote_updates(intent_id, run_id, ts, yes_bid_units, yes_ask_units,
       yes_ask_size_fp, volume_fp, PRIMARY KEY(intent_id,run_id))
fill_evidence(intent_id PK, evidence_type, evidence_ts, trade_id,
       quote_run_id, fill_price_units, proof_json)
settlement_revisions(settlement_revision_id PK, ticker, result,
       expiration_value, cli_artifact_id, market_artifact_id,
       observed_ts, supersedes_id, mismatch_state)
regime_assignments(assignment_id PK, gate_version, event_revision_id,
       storm_episode_id, computed_asof_ts, member_set_hash)
gate_runs(gate_run_id PK, asof_ts, gate_version, population_hash,
       rng_seed, metrics_json, decision)
```

要求：

- UTC 时间必须带 offset；local date、LST 窗口单列。
- 原始 artifact 与 settlement revision append-only；不得 UPDATE 覆盖历史事实。
- `INSERT OR IGNORE`/唯一键保证重跑幂等。
- DB 写入事务化；report/adjudicate 对 W3/W2 库都用 URI `mode=ro` 和 `PRAGMA query_only=ON`。
- W2 配对表不复制进 W2 库；按输入 hash 派生或缓存于 W3 库。
- 默认 DB 写失败不得影响任何现有 live 进程。

## 11. 结算、P&L 与两个空模型

只接受 Kalshi `settled/finalized` 且 result 为 YES/NO。保存 `expiration_value`，并与对应 NWS CLI 最大温交叉核验；不一致时 `quarantine_settlement_mismatch`，不进入主门，等待人工裁决。不得从相邻桶、价格或 ticker 猜 outcome。

W3 长 YES 的主 P&L：

```text
YES: contracts * (1 - maker_limit) - conservative_fee
NO:  -contracts * maker_limit      - conservative_fee
```

只有 F2_print/F2b_book 进入主 P&L。正式主退出为持有到结算；`45c` 退出仅可另报探索结果，不进入 V1 gate。

常设两个非晋升对照：

- `PT_null`：每 ticker 在 tau 窗内第一次 `mid_yes<15c` 的双边 snapshot，以当时正尺寸 yes ask 加 taker fee 买 1 张、持有结算。它是可见报价反事实，标 `print != fill`。
- `PM_null`：同一 price-only candidate 不看任何 q，以 `min(14c, bid 的下一合法 tick)` 建 1 张 maker intent；若该价不低于 ask，则尝试 join bid，否则记 unpostable。只按 F2 计 P&L。它检验“maker 本身是否救活纯价格阈值”，不参与晋升。

W2 原库只读，报告原口径及同城市日/同 tau 层对照，始终标 `print != fill`。在 W2 没有等价 F2 证据前，W2 差值不是硬门。

## 12. `W3_GATE_V1` 预注册晋升门

### 12.1 样本门

阶段 B 从零开始，同时满足：

- 日历跨度至少 45 天并跨一个月界；90 天为容量终点。
- `eligible_settled_tickers >= 300`：first-eligible 的 selected + eligible_not_selected unique tickers。
- `F2_filled_settled >= 90`。
- `eligible_city_days >= 100`，每城至少 10；city-day 键为 `(series, settlement_local_date)`。
- `settlement_dates >= 35`。
- 三个 decision tau 层各至少 20 个 settled F2 fills。
- storm eligible city-days 至少 20，覆盖至少 3 个 storm episodes、3 个城市；non-storm eligible city-days至少 60。

达不到只能 `ACCUMULATE`。不得因点估计漂亮提前通过。

### 12.2 双 CI 主门

CI 固定为 10,000 次非参数 percentile block bootstrap，固定 RNG seed。先把每个 settlement date 作为一个 block；若某个 storm episode 跨多个日期，则用 union-find 合并这些日期，保证同日多城和跨日 storm 都不拆。另报 city-day cluster 与 calendar-week sensitivity，但主裁决不切换口径。

1. **净 P&L CI**：只用 settled F2 intents。每 intent 先算 `net_pnl / max_loss`，同 city-day 多 intent（仅容量 V2 可能出现）按实际 shadow risk 聚合。均值 95% CI 下界必须 `>0`，累计净 P&L 也必须 `>0`。
2. **paired Brier CI**：对 first-eligible 的 selected + eligible_not_selected 计算

   ```text
   d_brier = (mid_yes - y)^2 - (q_trade - y)^2
   ```

   同 city-day 内先等权平均，再做 block bootstrap。`mean(d_brier)` 的 95% CI 下界必须 `>0`。

两门必须同时通过。Brier 过而 P&L 不过，结论为 `NO_EDGE_AFTER_EXECUTION`；P&L 过而 Brier 不过，结论为 `UNRELIABLE_MODEL_EDGE`。二者都不授权自动实盘。

### 12.3 否决、容量与版本纪律

- 任一城市达到 20 个 F2 fills 后累计净 P&L `<0`：V1 不得整体晋升。删城必须开新版本、全部重计。
- 任一 tau 层达到 20 个 F2 fills 后累计净 P&L `<0`：同上，不能事后删层重算。
- storm 或 non-storm 主层平均净 P&L `<0`：继续积累；不得声称跨体制 edge。
- 达到 120 个 eligible city-days 后，任一主 CI 上界 `<=0`：`ARCHIVE_V1`。
- 第 30 天冻结计算 `projected_F2_at_90d = 3 * F2_by_day30`。若 `<90`，V1 标 `INCONCLUSIVE_CAPACITY_V1`。预登记的 V2 可每分派城市日最多选两只、总 shadow risk 仍为 `$1`、各最多 `$0.50`；V2 的时钟和全部计数归零，禁止与 V1 pooling。
- 90 天仍不满足样本门：`INCONCLUSIVE_CAPACITY`，不放宽门。
- 每新增 50 个 eligible city-days 可出一次固定报告；任何阈值变化必须新版本。

## 13. 配置冻结值

```yaml
strategy_version: W3_NWS_TAIL_MAKER_V1
gate_version: W3_GATE_V1
shadow_only: true
series:
  - KXHIGHNY
  - KXHIGHCHI
  - KXHIGHAUS
  - KXHIGHMIA
  - KXHIGHLAX
  - KXHIGHDEN
  - KXHIGHPHIL
yes_mid_band: [0.01, 0.15]
tau_layers: [[2, 8], [8, 20], [20, 48]]
min_edge_lcb: 0.05
min_probability_ratio: 1.50
max_maker_price: 0.14
intent_ttl_hours: 6
intent_end_tau_h: 2
shadow_risk_unit_usd: 1.00
fill_policy: F2_print_or_F2b_book
model_bootstrap_reps: 2000
gate_bootstrap_reps: 10000
```

闭区间语义：每个 tau 层为 `(lo,hi]`；mid 为 `[0.01,0.15)`。

## 14. 施工顺序与交付

1. 先实现 schema、artifact 证据链、结构化 strike/LST/price-grid 纯函数。
2. 实现无策略门的全量采集和 append-only 结算。
3. 实现阶段 A 四族 OOF、manifest 和 deterministic q/LCB。
4. 实现阶段 B 分层、maker 枚举、intent lifecycle 和 F2 证明。
5. 实现 PT/PM null、W2 只读 comparator、报告和 gate。
6. 用 fixture + 临时 SQLite 完成 smoke；再做一次公开 Kalshi/NWS GET-only、临时库 `--once` smoke。

最低命令：

```text
python -m py_compile src/wxtail.py scripts/wxtail_shadow.py scripts/wxtail_smoke.py
python scripts/wxtail_smoke.py --db <temp>/wxtail_smoke.db
python scripts/wxtail_shadow.py --help
python scripts/wxtail_shadow.py collect --once --db <temp>/wxtail_public.db
python scripts/wxtail_shadow.py report --db <temp>/wxtail_public.db
```

不要运行 `tests/` 或 pytest。公开 smoke 不得使用交易客户端、认证或写网络请求。

交付时附：文件清单、schema version、manifest 示例、fixture/smoke 输出、网络方法清单、默认库未被 smoke 修改的证明、现有 live 文件零 diff 的证明，以及所有已知限制。Opus 完成施工后，Sonnet 按 `wx_review_criteria.md` 独立验收；未通过不得接调度。
