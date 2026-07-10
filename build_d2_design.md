# D2 WEATHER 数据裁决与影子挑战设计

状态：Codex 5.6-sol 数据/设计席定案稿，待 Fable 5 架构席 review  
数据截点：2026-07-09 22:42 MDT（2026-07-10 04:42 UTC）  
范围：只读审计、联网核实、设计与实现规格；本席没有写实现代码，也没有改任何实盘参数或实盘模块。

## 0. 一页裁决

D2 继续建设，但要改写当前叙事。

- W1 的已结算实盘 P&L 是正数：10 笔、8 个城市日、净 `+$1.29`，投入成本 `$3.71`。不过利润主要来自 MIA 2026-07-08 一笔 2 张 YES 的 `+$1.68`；10 笔中只有 4 笔盈利。
- W1 的概率质量不合格：模型 Brier `0.3135`，同期入场市场概率 Brier `0.2294`。配对差 `market Brier - model Brier = -0.0840`，城市日聚类 bootstrap 95% CI `[-0.3302, +0.1736]`。点估计输市场，样本又不足以排除偶然。
- W2 的小额实盘样本仍为正：已结算 8 笔净 `+$0.62`。但真正负责裁判的首触影子样本已经反证旧回测：81 个已结算市场、27 个城市日，按每市场 1 张、站立 `no_ask` 加记录费率计算，净 `-$3.74`，平均 `-4.62c/张`；城市日聚类 95% CI `[-7.74c,-1.05c]`。该口径仍是 `print != fill`，不能当实盘成交证据，但它已经足以否决“W2 当前稳定挣钱”的说法。
- `<15c` 尾部有方向性信号，没有可晋升证据。`weather_cal.db` 中 31 个 `<15c` 桶只有 16 个能从另外两库按 exact ticker 找到结果；2 个命中，realized `12.5%` 对平均 implied `7.19%`，差 `+5.31pt`，城市日聚类 95% CI `[-6.68pt,+23.35pt]`。两个命中都来自 MIA；NY 和 PHIL 为 0 命中。缺失结果并非随机，且没有 AUS/CHI/DEN/LAX、跨季或 storm 字段。
- 因此不复制纯价格阈值。新增“模型条件尾部挑战组”，用 `<15c` 只定义候选集，入组必须满足站点级 NWS 概率下界和净优势门，并以保守 maker 成交证明计 P&L。它与 W2 同期、同城市日、同风险单位前向比较。
- 挑战组只能从影子开始。即使通过，也只能形成上线提案；真钱上限、恢复预算、提高风险、修改验收门均由用户裁决。

P&L 是首要裁判。Brier 只负责阻止一个靠偶然命中赚钱、概率却系统失真的模型被放大。

## 1. 约束与审计边界

本设计遵守以下边界：

1. 三个 SQLite 库都通过 URI `mode=ro` 打开，并立即执行 `PRAGMA query_only=ON`：
   - `data/ledger.db`
   - `data/weather_cal.db`
   - `data/wxfade_shadow.db`
2. 没有读取或修改 `D:\kalshi-secrets`。
3. 没有运行 `tests/`，没有实例化真实下单客户端，没有提交任何订单。
4. 没有修改 `src/weather.py`、`src/wxfade.py`、`src/pipeline.py`、`scripts/quant_loop.py` 或 `config.yaml`。
5. `build_shared.txt` 在当前工作区及忽略文件中均未找到。本稿以用户消息中的共享铁律和 `CLAUDE.md` 第 9 条为准。
6. 工作树已有用户改动：`data/quant_loop.log`、`research/VALUES.md` 及若干未跟踪文件。本稿没有触碰这些文件。

证据等级分开记录：

| 证据 | 口径 | 可用于什么 |
|---|---|---|
| W1 `ledger.db` live settled | 已有真实成交和已实现 P&L | 描述当前 W1 实盘战绩；样本很小 |
| W2 `ledger.db` live settled | 已有真实成交和已实现 P&L | 描述被 live 选择器挑中的 8 笔；不能代表全候选集 |
| W2 `wxfade_shadow.db` | 首次看到的站立报价，没有真实订单 | 前向机制筛查；必须附 `print != fill` |
| `weather_cal.db` | 扫描时模型和 mid | 概率诊断；库本身没有 outcome，不能独立算 Brier |
| gopfan2 官方榜单/个人页 | 钱包级、类别级聚合 | 核实历史规模和近期 P&L；不能归因到某一条规则 |
| 第三方文章/X 讨论 | 二手重建 | 只生成待测假设，不能作为 Kalshi 上线证据 |

## 2. 三库数据裁决

### 2.1 W1 实盘：逐城与逐季

W1 定义为 `mode='live' AND title LIKE 'weather KXHIGH%'`，排除 `weather-fade`；Brier 只用 `status='settled' AND result IN ('yes','no')`。`q_consensus` 是 YES 概率，`market_prob` 是同方向入场市场概率，结果统一编码为 YES=`1`、NO=`0`。

| 城市/series | 已结算 n | 城市日 | 净 P&L | 成本 | ROI/成本 | 模型 Brier | 市场 Brier | 市场减模型 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| KXHIGHMIA | 5 | 5 | +$1.02 | $1.98 | +51.5% | 0.3862 | 0.2524 | -0.1338 |
| KXHIGHNY | 2 | 1 | +$0.25 | $0.75 | +33.3% | 0.1214 | 0.2211 | +0.0997 |
| KXHIGHPHIL | 3 | 2 | +$0.02 | $0.98 | +2.0% | 0.3204 | 0.1968 | -0.1236 |
| **合计** | **10** | **8** | **+$1.29** | **$3.71** | **+34.8%** | **0.3135** | **0.2294** | **-0.0840** |

AUS、CHI、DEN、LAX 没有 W1 已结算成交。全部样本都在 2026 年 7 月，属于气象学夏季；秋、冬、春均为 `n=0`。因此“逐季表现”目前只有一行：Summer 2026 `n=10, P&L=+$1.29, Brier=0.3135`。不能外推到其他季节。

这组数据的含义不是“Brier 不重要”。它说明当前 W1 可能靠少数大赔率命中赚钱，同时大多数概率偏离市场。若直接加尺寸，P&L 方差会先放大，模型错误也会一起放大。

### 2.2 `weather_cal.db` 不能完成原本承诺的校准任务

当前库只有一张表：

```text
buckets(ticker, ts, q_model, mid, local_hour)
```

截至截点：

- 59 行，59 个 distinct ticker，2026-07-05 至 2026-07-09，共 5 天。
- 每行都在 `local_hour=11`；没有午后、过峰或晚间样本。
- 只覆盖 MIA 19 行、NY 14 行、PHIL 26 行；另外四城为 0。
- 没有 `result`、结算温度、station、NWS forecast issue time、obs max、forecast max、sigma、season、storm、bid/ask、fee 或成交状态。
- 部分看似完整的城市日中，模型桶概率之和超过 1。例如 NY 2026-07-08 的记录和为 `1.1945`，PHIL 2026-07-06 为 `1.1180`。独立给每个桶加 2.5% floor 会破坏事件级概率守恒。

根因在现有调用顺序：`cmd_weather` 在调用 `candidates()` 和写校准库之前，先检查天气家庭日入场帽；帽已满就直接返回。W2 也占用同一天气家庭帽，所以“每次扫描记录全部桶”的注释与实际行为不一致。结果是校准仪器被交易门截断，只留下东部时区上午第一次扫描。

修复原则：采集/校准必须先于任何交易资格、预算和城市帽。采集失败可以阻止交易；交易帽不能阻止采集。

### 2.3 W2 fade：影子与 live 必须分开看

`wxfade_shadow.db` 的规则是 YES mid 在 `[0.15,0.40]`、tau `(8,48]h`，假设买 1 张 NO。已结算 81 个市场，未结算 44 个，覆盖 6 个入组日、27 个城市日。

| series | n | 城市日 | YES 命中 | 平均 YES mid | 影子净 P&L | 平均/张 |
|---|---:|---:|---:|---:|---:|---:|
| KXHIGHAUS | 12 | 4 | 4 | 27.21% | -$1.07 | -8.92c |
| KXHIGHCHI | 11 | 4 | 3 | 26.55% | -$0.58 | -5.27c |
| KXHIGHDEN | 14 | 4 | 4 | 25.36% | -$1.02 | -7.29c |
| KXHIGHLAX | 11 | 4 | 2 | 24.23% | +$0.34 | +3.09c |
| KXHIGHMIA | 10 | 4 | 3 | 22.95% | -$0.96 | -9.60c |
| KXHIGHNY | 7 | 3 | 1 | 25.64% | +$0.58 | +8.29c |
| KXHIGHPHIL | 16 | 4 | 4 | 22.91% | -$1.03 | -6.44c |
| **合计** | **81** | **27** | **21** | **24.88%** | **-$3.74** | **-4.62c** |

实际 YES 命中率 `25.93%`，Wilson 95% CI `[17.63%,36.40%]`。分 tau 后差异很大：

| tau | n | YES 命中 | 净 P&L | 平均/张 |
|---|---:|---:|---:|---:|
| `(8,20]h` | 8 | 0 | +$1.80 | +22.50c |
| `(20,48]h` | 73 | 21 | -$5.54 | -7.59c |

这与旧注册簿中“20-48h 194-1、最优”的回测结论正面冲突。可能原因包括季节漂移、历史回填选择偏差、首触定义不一致、把互斥桶当独立样本，或真实盘口已经修复偏差。现在不能选一个喜欢的解释；只能冻结规则并继续前向记录。

W2 live 是另一个样本：13 行中 8 已结算、2 open、3 voided；已结算 6 盈 2 亏，净 `+$0.62`，成本 `$4.78`。live 选择器只挑便宜 NO，并受家庭帽、城市帽和 IOC 成交影响，所以它不能推翻全候选影子为负的结论。

### 2.4 `<15c` 尾部证据

`weather_cal.db` 没有结果。本席只用 exact ticker 从 `ledger.db` 和 `wxfade_shadow.db` 找结果，不从价格或相邻桶猜结算。31 个 `<15c` 桶中只有 16 个匹配到结果。

| mid 桶 | weather_cal 全部 | exact resolved | YES 命中 | realized | resolved 平均 implied |
|---|---:|---:|---:|---:|---:|
| `<3c` | 10 | 4 | 0 | 0.0% | 2.00% |
| `[3c,5c)` | 5 | 4 | 0 | 0.0% | 4.25% |
| `[5c,10c)` | 8 | 2 | 0 | 0.0% | 8.50% |
| `[10c,15c)` | 8 | 6 | 2 | 33.3% | 12.17% |
| **`<15c`** | **31** | **16** | **2** | **12.5%** | **7.19%** |

按城市看，MIA 为 `2/6`，平均 implied `9.92%`；NY 为 `0/4`，平均 implied `3.50%`；PHIL 为 `0/6`，平均 implied `6.92%`。两个命中是：

- `KXHIGHMIA-26JUL06-B93.5`，mid `12c`，当时 W1 q=`2.5%`，结果 YES。
- `KXHIGHMIA-26JUL08-B91.5`，mid `14c`，当时 W1 q=`62.47%`，结果 YES。

在这 16 个 exact-resolved 尾部桶上，W1 模型 Brier `0.1093`，市场 Brier `0.0996`。模型没有显示出比市场更好的尾部概率。

裁决：现有数据只支持“10-15c 的 MIA 桶值得前向挑战”，不支持“所有 `<15c` 桶被系统性低估”。exact-result 覆盖取决于它是否被 W1/W2 选中，缺失非随机；样本也没有 storm 标记和跨季覆盖。该证据等级不足以上线。

## 3. gopfan2 核实结果

### 3.1 官方可核实事实

截至联网核实时：

- [Polymarket 天气 all-time 榜单](https://polymarket.com/leaderboard/weather/all/profit)显示 gopfan2 排名第 1，天气 P&L 约 `+$354,275`，天气成交量约 `$4,607,415`。
- [gopfan2 官方个人页](https://polymarket.com/@gopfan2)显示 2024 年 8 月加入、`2,024` 个 predictions、最大单笔胜利 `$920K`。这与“几万次独立下注”的说法不一致；链上 fill/transfer 可能有几万条，但官方 prediction 数不是几万。
- 官方 Data API 的同钱包天气 P&L：近 1 日 `+$140.48`、近 1 周 `-$3,384.17`、近 1 月 `-$1,829.92`、all-time `+$354,274.64`。查询入口是 [Polymarket leaderboard API](https://data-api.polymarket.com/v1/leaderboard?category=WEATHER&timePeriod=MONTH&orderBy=PNL&limit=1&offset=0&user=0xf2f6af4f27ec2dcf4072095ab804016e14cd5817)。榜单 P&L 可能含持仓 mark，不等于已实现策略 P&L。
- 官方 activity 显示该钱包现在也大量交易非天气市场，且单次成交可远高于 `$1`。所以“每注约 `$1`”最多是某个历史天气子策略的描述，不是当前钱包的全局风险规则。

网上常见的 `$1.48M` 或 `$2M+` 说法与当前官方天气榜单不符，可能混合了全品类 P&L、不同时间点、未实现收益或第三方归因。本设计只采用官方 `$354K` 天气口径。

### 3.2 机制重建及可信度

两个可访问的二手重建有共同部分：

- [Print Money Lab Episode 1](https://www.printmoneylab.com/2026/03/weather-bot-episode-1-betting-on-temperature-polymarket.html)称其查看链上历史后，观察到低于 `15c` 的 YES、小额、多市场重复。
- [Episode 4](https://www.printmoneylab.com/2026/03/weather-bot-episode-4-simple-price-rules-beat-complex-math.html)进一步称，低价只是候选，预报要“大致指向”该桶；价格涨到约 `45c` 时常提前卖出，不一定持有到结算。
- [Medium 汇总](https://medium.com/mountain-movers/people-are-making-millions-on-polymarket-betting-on-the-weather-and-i-will-teach-you-how-24c9977b277c)则把另一条腿描述为：当模型否定一个 YES 价格高于 `45c` 的桶时买 NO。

因此 `45c` 有两种互相冲突的解释：低价 YES 的退出价，或高价 YES 桶的反向 NO 入场条件。没有 gopfan2 本人的规则文档，也没有公开、可复算的逐笔归因表来裁决。可靠的共同核心只有：

1. 价格阈值用于发现候选，不应单独决定交易。
2. 条件来自精确结算站点的天气模型/观测。
3. 小额、广覆盖、自动化执行适合薄尾盘口。
4. 报价重定价本身可能是利润来源，不一定靠最终命中。

### 3.3 现在还有效吗

答案是“历史 edge 真实，当前是否仍有正 edge 未证实”。

支持仍可能有效的证据：gopfan2 仍为官方天气总榜第一，最近 1 日仍为正；公开市场中仍有大量薄尾价和散户使用错误站点/手机天气的情形。

支持已经压缩的证据：官方近周和近月天气 P&L 为负；天气总榜已有大量高成交量账户和明确以 bot 命名的账户；开源天气机器人、模型聚合服务和自动化模板已普及。[VegaForge 的 2026 年汇总](https://vegaforge.dev/blog/weather-bots-polymarket)也明确把 margin compression 列为当前风险，但它仍是二手判断。

这两组证据不能识别“bot 导致压缩”的因果关系。近期亏损也可能是天气体制、持仓 mark 或钱包策略变化。结论只能由我们自己的冻结前向组给出。

还要注意平台迁移风险：gopfan2 的公开重建主要来自 Polymarket，结算站点、温度取整、盘口、费用和 maker 规则与 Kalshi KXHIGH 不同。外部成功只授权挑战，不授权复制上线。

## 4. 模型条件尾部挑战组

### 4.1 假设

正式假设冻结为：

> 在 Kalshi KXHIGH 日高温市场中，若精确结算站点的 NWS 条件概率下界仍显著高于可成交的 `<15c` YES maker 价，则这些尾部桶在费用后有正 P&L；纯 `<15c` 阈值本身没有被假定为正 edge。

挑战组代号 `W3_NWS_TAIL_MAKER_V1`。W2 继续按现行规则记录，作为同期基线；本设计不改 W2 实盘或影子参数。

### 4.2 两阶段启动

#### 阶段 A：仪器与训练，不计正式胜负

先连续采集至少 60 个 settled city-days，并满足每城至少 6 个 city-days。所有扫描都记录，不受交易帽影响。阶段 A 只做以下工作：

- 保存 exact station、规则摘要 hash、NWS forecast issue/update time、逐小时预报、逐小时观测和最终 settled high。
- 建立 `forecast_error = settled_high - information_set_forecast` 的站点级分布。
- 用 rolling-origin 验证选择一个模型版本；不得随机切分同一天或把结算后数据回灌到早期 snapshot。
- 冻结模型代码 hash、训练数据截止时刻、参数、阈值和 schema version。

阶段 A 可以同时输出“非正式仪器 P&L”，但这些结果不得进入晋升门。正式计数从模型冻结后的下一次完整扫描开始归零。

#### 阶段 B：冻结前向挑战

阶段 B 不再拟合参数。任何 bug 修复若改变 q、候选、maker 价、fill 判定或结算口径，必须升 `strategy_version` 并重启正式计数；纯日志/展示修复可保留计数，但要记录 migration。

### 4.3 站点级 NWS 概率

随机变量是该结算站在市场规则日界内的最终日高温 `H`。信息集只包含扫描时已经发布的数据：

- NWS station observations：当日已观测最高值和观测时间/质量标记。
- NWS hourly point forecast：剩余规则日内每小时温度路径及其更新时间。
- station、local standard time 日界、lead time、local hour、season。
- regime：storm/non-storm、锋面/对流代理、预报路径内最大逐时温差、近期 forecast revision。

`H` 的预测分布不用当前“高斯 + 每桶 2.5% floor”。V1 采用分层经验残差：

1. 主中心 `mu = max(observed_max, forecast_remaining_max)`；过峰后只有在历史条件显示剩余升温概率足够低时才能退化到 observed max。
2. 残差按 `station x lead_band x local_hour_band x season x storm` 分层；样本不足时依次向 station、气候区、全局分布 shrink。
3. 用经验 CDF 或 Student-t/核平滑混合保留肥尾，不给每个桶独立加 floor。
4. 按市场的真实整数/阈值边界对整条 `H` 分布积分；同一互斥事件的桶概率必须非负且总和为 1（允许因未展示/无报价桶造成记录子集小于 1）。
5. 输出 `q_raw`、校准后的 `q_cal` 和不确定性下界 `q_lcb`。`q_lcb` 使用训练城市日 block bootstrap 的 10% 分位，作为保守 one-sided 90% 下界；它是入组信号，不是报告 CI。

为修复 W1 Brier 输市场的问题，同时保留独立信息，模型保存两条概率：

- `q_met`：只用气象信息的独立概率。
- `q_trade`：用训练期外样本估计的 reliability weight 在 log-odds 上把 `q_met` 向 contemporaneous market mid shrink。若气象模型没有增量，权重自动接近 0，挑战组就不会制造虚假大 edge。

正式 Brier 同时报告两者，但入组使用 `q_trade_lcb`。市场价格只参与 shrink 和比较，不参与 outcome 回填。

### 4.4 候选、入组与去相关

所有条件必须同时满足：

1. series 在当前 7 个 KXHIGH 城市中，ticker 解析成功，规则关键词与 exact station 一致。
2. `8 < tau_h <= 48`，与 W2 前向窗口一致。
3. YES 双边报价存在，`0.01 <= mid_yes < 0.15`。`<15c` 只定义尾部候选。
4. NWS forecast 和 observation legs 通过阶段 A 冻结的数据完整性规则。
5. `q_trade_lcb - maker_limit - fee_reserve_per_contract >= 0.05`。
6. `q_trade_lcb / maker_limit >= 1.50`。
7. 规则日、station、forecast issue time 或 outcome source 任一含糊时跳过，不靠默认值猜。

每个 ticker 只允许一个正式 intent，第一次满足全部条件的 snapshot 拥有入场权。为避免同一天买一排互斥桶，主口径每城市日只选 `q_trade_lcb - all_in_limit` 最大的一个候选；其余记录为 `eligible_not_selected`，可用于 Brier，不能计主 P&L。

### 4.5 storm 预注册定义

`storm_flag_v1=1` 当且仅当市场规则日内满足至少一项：

- NWS alert 在站点覆盖区生效，event type 属于 Tornado、Severe Thunderstorm、Flash Flood、Winter Storm、Blizzard、Ice Storm；或
- NWS hourly 路径出现 thunderstorm 文本，且同一小时 `probabilityOfPrecipitation >= 50%`；或
- 冻结的锋面/对流代理触发：连续 3 小时内预报温度变化绝对值 `>6F`。

保存命中的原始 alert id、forecast period 和规则版本。Heat Advisory/Excessive Heat Warning 单独记为 `heat_regime`，不计入 storm 配额；否则夏季高温会把 storm 覆盖虚增。

### 4.6 maker 影子执行

这是影子订单，不提交到任何交易所。

1. `tick` 从市场报价精度读取；若 API 没给，使用 Kalshi 当前最小价格单位并写明来源。
2. 初始 maker limit 向下量化：

   ```text
   raw_limit = min(0.14,
                   yes_bid + one_tick,
                   q_trade_lcb - 0.05 - fee_reserve_per_contract)
   ```

3. 必须满足 `yes_bid <= maker_limit < yes_ask`；会立即吃单的报价不算 maker 挑战。
4. `fee_reserve` 默认按同价格、同张数的 taker fee 计算，直到取得并冻结适用 maker 费表。这样不会用“可能免 maker fee”美化影子 P&L。
5. 固定 `$1` 只作为影子风险归一化，不是实盘美元上限提案。选择满足 `contracts * maker_limit + fee_reserve <= $1.00` 的最大整数张数，至少 1 张。
6. intent TTL 为 6 小时、NWS forecast revision 或距离 close 8 小时，三者先到者为准。未填前若 `q_trade_lcb` 跌破 break-even，影子取消。

fill 证据分层：

| 层级 | 条件 | 是否计主 P&L |
|---|---|---|
| F0 intent | 只发布假想限价 | 否 |
| F1 touch | 后续 ask/last 到达 limit，但没有穿价/量证据 | 否，只报上界 |
| F2 trade-through | intent 之后、TTL 之前，后续 YES ask 严格低于 limit；或公开逐笔成交低于 limit 且成交量增加 | **是** |
| F3 demo fill | `KalshiLive(demo=True)` 的 demo 成交 | 否，按共享铁律仅为 D 类机制证据 |

若以后能可靠取得当时 queue ahead 和逐笔成交，新增 F2Q 队列模型；不得回改 V1 的历史 fill。`print != fill` 警告必须出现在所有 F0/F1 报告中。

主口径持有到结算，用于把气象概率、Brier 和 P&L 对齐。`45c` 动态退出另记 `exploratory_exit45`：若 bid 到 `45c`，按可卖 bid 模拟退出。它不参与 V1 晋升，因为外部资料对 `45c` 的含义有冲突，而且当前库没有完整价格路径。

### 4.7 W2 同期比较

W2 原规则和 DB 不改。新报告层做两种比较：

1. 原样 W2：保持现有 `wxfade_shadow.report()` 的每市场 1 张结果，附 `print != fill`。
2. 公平城市日比较：在每个城市日，从 W2 首触记录中按现有 live 逻辑选 `no_ask + fee` 最低的一只；W3 选净 edge 最大的一只。两边都按 `$1` 影子最大损失归一化。只有两边都有候选的城市日进入 paired P&L；全部 W3 城市日另报绝对 P&L。

配对键是 `(series, settlement_local_date)`，不是扫描时间。一个 synoptic day 的多城结果仍相关，所以 CI 按 settlement date 成块 resample，storm 跨日则按 `storm_id` 合并为更大的 block。

## 5. 预注册晋升门

### 5.1 样本门

正式阶段 B 同时满足以下最小值后才允许裁决：

- 日历跨度至少 45 天，跨至少一个月界。
- `n_intent_settled >= 300` 个 unique ticker；重复扫描不加 n。
- `n_F2_filled >= 120` 个主 P&L maker fills。
- `city_days >= 100`，7 城每城至少 10 个 settled city-days。
- `settlement_dates >= 35`；同一天多城不被当成 7 个完全独立天气系统。
- storm city-days 至少 20，覆盖至少 3 个 `storm_id`、至少 3 个城市；non-storm city-days 至少 60。
- W2/W3 同城日 paired 样本至少 60。

达不到样本门只能 `ACCUMULATE`，不能用漂亮点估计提前晋升。

### 5.2 两个主 CI 与一个比较门

所有 CI 都在冻结代码中用 10,000 次非参数 block bootstrap 计算，主 block 为 settlement date；连续 storm 日按 storm id 不拆。报告同时给 city-day cluster sensitivity。主裁决用双侧 95% CI 的下界。

1. **净 P&L 主门**

   `mean net P&L per $1 shadow risk` 的 95% CI 下界 `>0`，且累计净 P&L `>0`。只用 F2 fills、实际结算和保守 fee reserve。

2. **配对 Brier 门**

   对所有 selected intents（不按 fill 筛选）计算：

   ```text
   d_brier = (market_mid - y)^2 - (q_trade - y)^2
   ```

   `mean(d_brier)` 的 95% CI 下界 `>0`。这表示模型在完全相同的 ticker/snapshot 上显著优于市场概率。

3. **W2 前向比较门**

   paired city-day 的 `W3 net P&L - W2 net P&L` 95% CI 下界 `>0`。若 W3 自身为正但不优于 W2，继续影子，不晋升为替代腿。

三门必须同时通过。P&L 门优先；Brier 通过而 P&L 不通过，裁决为 `NO EDGE AFTER EXECUTION`。

### 5.3 分层否决与停止规则

即使总样本通过，以下任一情况触发否决或继续积累：

- 任一城市有至少 20 个 F2 fills 且累计净 P&L `<0`：该城市不得随总组晋升，必须单独排除并重新预注册；不能事后删城后沿用同一 CI。
- storm 或 non-storm 任一主层平均净 P&L `<0`：不允许声称跨体制 edge；继续积累到两层 CI 都不为负。
- 120 个 city-days 后，净 P&L 或 paired Brier 的 95% CI 上界 `<=0`：`ARCHIVE_V1`。
- 90 天后仍未满足样本门：`INCONCLUSIVE_CAPACITY`，只说明机会/成交容量不足，不放宽门。
- 每完成 50 个新 city-days 可出一次固定格式状态报告，但不得改阈值。任何正式参数变更开 V2，V1 留档。

通过后的动作只有：生成带完整判据表的上线提案，交 Fable review 和用户裁决。不得自动 wire 进 pipeline，不得提高美元上限，不得真实下单。

## 6. W1 改进路线

### 6.1 先修仪器

W1 现在最需要的不是再改一个 sigma 数，而是得到能复算的训练/评估数据。

每次扫描必须先记录：

- `event_key/series/ticker/station/rules_hash/settlement_local_date`
- `scan_ts_utc/local_hour/tau_h/nws_issue_ts/nws_update_ts`
- `obs_max_f/obs_latest_ts/forecast_hourly_path/forecast_remaining_max_f`
- `q_raw/q_met/q_trade/q_lcb/model_version`
- `yes_bid/yes_ask/no_bid/no_ask/mid/last/volume`
- `storm_flag/storm_id/season/regime_version`
- 结算后的 `result/settled_high_f/outcome_source/settled_ts`

采集路径不读账户、不看预算、不看已有持仓。交易 disabled、日帽已满或账户认证失败时，校准采集仍应继续。

### 6.2 修正概率模型

建议顺序：

1. 实现 NWS Local Standard Time 规则日界，解决夏令时民用午夜与气候日界错位。
2. exact station 和规则 hash 每事件验证，不只检查第一个 market。
3. 用站点/lead/local-hour/season/storm 的残差分布替换固定高斯 sigma 和独立 2.5% floor。
4. event-level 统一归一化，保证互斥桶概率守恒。
5. 对模型进行 rolling-origin 校准；城市样本少时做分层 shrink，禁止每城用几个点独立拟合。
6. 用 market-anchored reliability blend 降低 Brier；只有模型增量在训练外稳定时才给它较高权重。
7. 交易门在嵌套、时间顺序 CV 中按费用后 P&L 选择，然后冻结前向；不能用同一批 forward 结果调门再验收。

`_bucket_prob` 的桶边界数学已经过现有评审，本设计不要求“修复”它。要改的是输入分布、事件级守恒、日界和校准。

### 6.3 W1 的新评估表

每周只出冻结表，不自动调参：

- 逐城、逐季、storm/non-storm 的 n、城市日、P&L、成本、ROI、最大城市日亏损。
- 模型与市场的 paired Brier、log loss、校准 slope/intercept。
- taker/maker、F0/F1/F2 分开的 P&L；任何 print 口径都带警告。
- 机会集、selected、intent、fill、settled 的漏斗，防止只看成交赢家。

W1 只有在费用后 P&L CI 为正时才能扩大；Brier 改善不能替代 P&L。

## 7. 给 Opus/Sonnet 的实现规格

### 7.1 模块选择

推荐新增 `src/wxtail.py`，不要把尾部逻辑塞进 `src/weather.py` 或 `src/wxfade.py`。

可复用：

- `src.weather.CITIES` 的 series/station/坐标/时区映射，但启动时复制到 snapshot 并做规则核验。
- `src.kalshi_client.KalshiPublic`、`normalize_market`、`taker_fee_usd`。
- `src.weather` 已验证的桶边界语义可作为 parity oracle。

不复用：

- `wxfade.scan()`：方向、价格带、首触键和 schema 都不同。
- `wxfade_shadow.db` 写路径：只能在报告器中以 `mode=ro` 读作 comparator。
- `weather.candidates()`：它把采集、时间门、报价筛选和当前 W1 概率耦合在一起，且不能提供正式挑战所需的 forecast metadata。

`wxtail.py` 内部先实现独立、纯函数式的 event distribution 和 bucket integration。未来若 Fable 批准，可把公共概率核心抽到新的 `src/weather_prob.py`，再让 W1 迁移；首次施工不得为了复用而修改当前 live-loaded `weather.py`。

### 7.2 强制 API

```python
@dataclass(frozen=True)
class TailOpportunity:
    opportunity_id: str
    strategy_version: str
    ticker: str
    series: str
    station: str
    event_key: str
    settlement_local_date: str
    scan_ts: str
    tau_h: float
    q_met: float
    q_trade: float
    q_lcb: float
    yes_bid: float
    yes_ask: float
    mid_yes: float
    maker_limit: float
    contracts: int
    storm_flag: bool
    storm_id: str | None

def scan_shadow(cfg: Mapping, *, now=None, db_path=None,
                market_source=None, nws_source=None) -> ScanReport: ...

def refresh_shadow(cfg: Mapping, *, now=None, db_path=None,
                   market_source=None, nws_source=None) -> RefreshReport: ...

def settle_shadow(*, now=None, db_path=None,
                  market_source=None) -> SettleReport: ...

def report_shadow(*, db_path=None, wxfade_db=None) -> TailReport: ...

def adjudicate_shadow(*, db_path=None, wxfade_db=None,
                      gate_version="W3_GATE_V1") -> GateReport: ...
```

所有外部源可注入，便于 fixture smoke。默认模块不得 import `KalshiLive`。CLI 只提供 `collect/refresh/settle/report/adjudicate`，显式拒绝 `--live`。

### 7.3 新影子库

新库：`data/wxtail_shadow.db`。建议 schema：

```text
schema_meta(version, created_ts)
runs(run_id, scan_ts, strategy_version, code_hash, config_hash,
     model_hash, source_status, error_text)
forecasts(run_id, series, station, settlement_local_date,
          nws_issue_ts, nws_update_ts, obs_max_f, obs_latest_ts,
          forecast_remaining_max_f, hourly_json, season,
          storm_flag, storm_id, regime_version)
quotes(run_id, ticker, yes_bid, yes_ask, no_bid, no_ask,
       mid_yes, last_price, volume, tau_h)
opportunities(opportunity_id, strategy_version, ticker, event_key,
              first_eligible_ts, q_met, q_trade, q_lcb,
              maker_limit, contracts, fee_reserve, selected_reason,
              status, PRIMARY KEY(strategy_version, ticker))
quote_updates(opportunity_id, ts, yes_bid, yes_ask, last_price,
              volume, fill_evidence, fill_ts, fill_price)
settlements(ticker PRIMARY KEY, result, settled_high_f,
            outcome_source, settled_ts)
w2_pairs(opportunity_id, w2_ticker, pair_key, w2_entry_ts,
         w2_no_ask, w2_fee)
```

要求：

- UTC ISO-8601 带 offset；local date 单独存。
- 所有首次资格判断使用 `INSERT OR IGNORE`，重跑幂等。
- 原始 NWS hourly JSON 可压缩存储，但必须保留 `sha256` 和关键规范化字段。
- 结果修订不能覆盖旧值；追加 revision/audit row。
- report/adjudicate 对本库和 W2 库都用只读连接。
- DB 写失败只影响新影子命令，不能传播到 live pipeline。

### 7.4 配置隔离

新增独立配置 `config/wxtail_shadow.yaml` 或模块内 versioned defaults；首次施工不要编辑现有 `config.yaml`。配置必须含：

```yaml
strategy_version: W3_NWS_TAIL_MAKER_V1
shadow_only: true
yes_mid_band: [0.01, 0.15]
tau_hours: [8, 48]
min_edge_lcb: 0.05
min_probability_ratio: 1.50
max_maker_price: 0.14
intent_ttl_hours: 6
shadow_risk_unit_usd: 1.00
fill_policy: trade_through
gate_version: W3_GATE_V1
```

`shadow_risk_unit_usd` 只是统计归一化。任何把它转成真钱上限的改动都需要用户明确授权。

### 7.5 施工与验证

1. 在隔离 git worktree 施工，或只新增上述模块/配置/fixture；不修改 live-loaded 文件。
2. 禁止运行 `tests/`。
3. 最低验证：
   - `python -m py_compile src/wxtail.py`
   - fixture + 临时 SQLite 的 collect/refresh/settle/report smoke
   - 一次公开 NWS/Kalshi read-only `--once --db <temp path>` smoke
4. 如任何 smoke 需要交易客户端，只能 `KalshiLive(demo=True)`；本规格本身不需要交易客户端。
5. smoke 验证以下不变量：
   - 同一 ticker 重跑不重复 intent。
   - settlement 前数据不能引用 settlement 后 NWS/market 字段。
   - F1 不计主 P&L，只有 F2 计。
   - event 概率和在完整互斥桶上为 1，误差容限 `1e-9`。
   - `mode=ro` 读取 W2 comparator。
   - `--live` 返回非零且不发网络写请求。
6. Opus/Sonnet 提交实现后，Codex 做数据/统计 review，Fable 做架构/wire review。只有 Fable 通过且用户知情后，才能另开任务把新命令接入调度；当前任务禁止 wire。

## 8. Review 记录

### Codex 5.6-sol 数据/设计 review

已审：`CLAUDE.md`、`research/WEATHER_LANES.md`、`src/weather.py`、`src/wxfade.py`、`src/kalshi_client.py`、`src/pipeline.py` 相关段落、三只指定 DB、官方 Polymarket 榜单/API/个人页及二手机制资料。

主要 findings：

| ID | 级别 | finding | 设计处置 |
|---|---|---|---|
| D2-DATA-1 | CRITICAL | calibration logger 被交易家庭帽提前返回截断 | 新采集器与交易门完全解耦 |
| D2-DATA-2 | HIGH | weather_cal 无 outcome/station/NWS snapshot，不能独立算 Brier | 新 schema 保存完整信息集和结算 |
| D2-MODEL-1 | HIGH | W1 Brier 输市场；独立 tail floor 可破坏概率守恒 | 分层残差、event normalization、market reliability shrink |
| D2-W2-1 | HIGH | W2 81 个 forward shadow 市场净负，20-48h 段尤差 | 冻结现状，只作 comparator，不再称稳定挣钱 |
| D2-TAIL-1 | HIGH | `<15c` 信号来自 16 个选择性结果，两个命中全在 MIA | 只授权模型条件挑战，不授权纯阈值 |
| D2-EXT-1 | MEDIUM | gopfan2 的 45c、$1、次数说法互相冲突 | 主门只用共同核心；45c 退出降为探索 |
| D2-EXEC-1 | HIGH | shadow quote 不是 fill | F2 trade-through 才计主 P&L，所有 print 带警告 |

本 review 没有修改代码、DB、配置或实盘状态。

### Fable 5 review

状态：`PENDING`。不得把本稿称为 Fable 已批准，也不得据此 wire 或上线。

```json
{
  "direction": "D2_WEATHER",
  "role": "codex5.6-sol_design_data",
  "as_of_utc": "2026-07-10T04:42:22Z",
  "implementation_written": false,
  "live_code_changed": false,
  "real_orders_sent": false,
  "database_access": {
    "files": [
      "data/ledger.db",
      "data/weather_cal.db",
      "data/wxfade_shadow.db"
    ],
    "sqlite_uri_mode": "ro",
    "query_only": true
  },
  "evidence": {
    "w1_live": {
      "settled_n": 10,
      "city_days": 8,
      "season": "summer_2026_only",
      "net_pnl_usd": 1.29,
      "cost_usd": 3.71,
      "model_brier": 0.313495,
      "market_brier": 0.229447,
      "paired_delta_market_minus_model": -0.084048,
      "paired_delta_cluster_ci95": [-0.330234, 0.173619]
    },
    "w2_shadow": {
      "settled_n": 81,
      "pending_n": 44,
      "city_days": 27,
      "yes_hits": 21,
      "net_pnl_usd_one_contract_each": -3.74,
      "mean_net_per_contract_usd": -0.046173,
      "mean_net_city_day_cluster_ci95_usd": [-0.077381, -0.01054],
      "evidence_warning": "print_not_fill"
    },
    "w2_live": {
      "settled_n": 8,
      "open_n": 2,
      "voided_n": 3,
      "net_pnl_usd": 0.62
    },
    "tail_under_15c": {
      "weather_cal_n": 31,
      "exact_resolved_n": 16,
      "yes_hits": 2,
      "realized_rate": 0.125,
      "mean_implied": 0.071875,
      "realized_minus_implied": 0.053125,
      "cluster_ci95": [-0.06675, 0.233462],
      "model_brier": 0.109273,
      "market_brier": 0.099588,
      "verdict": "directional_only_selection_biased_not_systematic"
    },
    "gopfan2_official": {
      "weather_all_time_pnl_usd": 354274.64,
      "weather_all_time_volume_usd": 4607415.41,
      "profile_predictions": 2024,
      "weather_day_pnl_usd": 140.48,
      "weather_week_pnl_usd": -3384.17,
      "weather_month_pnl_usd": -1829.92,
      "current_edge_verdict": "historically_real_currently_unproven"
    }
  },
  "decision": "BUILD_NEW_SHADOW_CHALLENGER_DO_NOT_WIRE",
  "challenger": {
    "strategy_version": "W3_NWS_TAIL_MAKER_V1",
    "module": "src/wxtail.py",
    "database": "data/wxtail_shadow.db",
    "candidate_mid": "0.01_to_less_than_0.15",
    "tau_hours": [8, 48],
    "min_edge_lcb": 0.05,
    "min_probability_ratio": 1.5,
    "max_maker_price": 0.14,
    "primary_fill": "F2_trade_through",
    "primary_exit": "hold_to_settlement",
    "exit45": "exploratory_only",
    "shadow_risk_unit_usd": 1.0
  },
  "promotion_gate": {
    "calendar_days_min": 45,
    "settled_intents_min": 300,
    "F2_fills_min": 120,
    "city_days_min": 100,
    "settlement_dates_min": 35,
    "each_city_days_min": 10,
    "storm_city_days_min": 20,
    "storm_ids_min": 3,
    "storm_cities_min": 3,
    "nonstorm_city_days_min": 60,
    "paired_w2_w3_city_days_min": 60,
    "net_pnl_ci95_lower_gt": 0.0,
    "paired_brier_delta_ci95_lower_gt": 0.0,
    "paired_pnl_vs_w2_ci95_lower_gt": 0.0,
    "automatic_live_promotion": false
  },
  "reviews": {
    "codex_design_data": "complete",
    "fable_architecture": "pending",
    "opus_sonnet_implementation": "not_started"
  }
}
```

## 9. 第二轮 (codex 回应 Fable)

本节是对 F-1 至 F-8 的正式回应。凡与前文冲突，以本节为准；它修订设计和后续施工规格，不授权实现、wire、实盘参数变更或下单。

### 9.1 F-1 — ACCEPT

公开 API 复核确认了 off-by-one。`GET /markets` 返回 `KXHIGHNY-26JUL10-T94` 的 `yes_sub_title="95° or above"`，`rules_primary` 为最高温 `greater than 94°` 才结算 YES；`KXHIGHNY-26JUL08-T83` 同样是 `84° or above` / `greater than 83°`。现行代码却从 ticker 取 `94`，在 T-high 分支用 `94-0.5=93.5` 切分，算成了取整后 `H >= 94`，多含一整个 `H=94` 的概率质量。以 `mu=94, sigma=2` 为例，这一档约为 19.7pt。

W3 改为从 `yes_sub_title` 和 `rules_primary` 解析实际 YES 集合，ticker 数字只做交叉校验：`or above` 的 subtitle 数必须等于 ticker strike `+1`，`or below` 必须等于 ticker strike `-1`；规则不完整、两字段互相冲突或指纹不符，一律跳过。§7.1 的 parity oracle 限于 B 桶和 T-low；T-high 必须使用新的规则语义 fixture。§6.2 “桶边界数学不要求修复”撤回。该 bug 会系统性抬高 T-high 的 q，是 W1 Brier 的机械性风险源；但它对现有 10 笔 aggregate Brier 的净贡献仍需按历史 snapshot 重放，不能仅凭方向把全部差额归因给它。

### 9.2 F-2 — COUNTER

接受把正式入组窗改为 `2 < tau_h <= 48`，并冻结三层 `(2,8]`、`(8,20]`、`(20,48]`。现有 `[8,48]` 确实漏掉了观测地板和过峰塌缩最可能产生增量的时段。`tau > 30h` 的独立信息不宜表述为严格等于零；市场和模型虽共享公开 NWS 输入，概率映射仍可能不同，但 W2 的 20-48h 前向结果足以要求该层单独受审。

反提案补两处自洽条件。第一，原 TTL 在“距离 close 8 小时”终止，与新 `(2,8]` 入组窗冲突；修订为 6 小时、下一次 NWS revision 或 `tau` 降至 2 小时，三者先到。第二，每个拟随组晋升的 tau 层都要有至少 20 个 F2 fills；达到 20 后累计净 P&L `<0` 即否决该层。被否决层不能在同一版本中事后删除后重算总门，只能排除后开新版本并重新计数。

### 9.3 F-3 — COUNTER

接受核心批评。严格说，原门并非数学上绝对不可达，因为 7 城在 90 天内最多可产生 630 个 city-days；但 `selected settled intents <= city_days`，要求 300 个 selected 尾部 intent 等价于要求至少 300 个触发 city-days。对稀疏尾部机会而言，这与 90 天容量裁决明显不匹配。

把 `settled_intents_min` 删除，改为 `eligible_settled_tickers_min >= 300`。它统计 first-eligible snapshot 上的 `selected + eligible_not_selected` unique tickers；重复扫描不加 n。paired Brier 同样扩到这两个状态，但先在每个 `(series, settlement_local_date)` 内等权平均，再按 settlement date/storm block bootstrap，防止某天出现更多互斥 eligible 桶便获得更高权重。300 是概率覆盖门，不再冒充可执行 intent 门。

F2 fills 下限降为 90，但只把它视为容量底线，不能称为 80% power。Fable 的 `(1.645*28/5)^2≈85` 只对应单侧 5% 阈值下约 50% 的越界概率，而且使用的是单张方差；本设计主门是每 `$1` 影子风险的双侧 95% block-bootstrap CI。即便暂用 `sd=28c` 的正态近似，均值 `5c` 要让期望的双侧 95% 下界刚好到 0，也需约 121 笔；要 80% power 约需 246 笔。90 笔之所以可作为最低裁决点，是因为 CI 下界 `>0` 仍是硬门：样本只有 90 时，观测 edge 必须更强才能通过。

接受第 30 天容量投影，但冻结公式和版本边界：`projected_F2_at_90d = 3 * n_F2_filled_by_day30`；若 `<90`，封存 V1 正式计数，启动 `W3_NWS_TAIL_MAKER_V2`，V2 的 45/90 天时钟和全部晋升计数从零开始，禁止与 V1 pooling。V2 每城市日按同一净 edge 排序最多选前两个 intent，但同一城市日的总 shadow risk 仍为 `$1`；有两个时各分配最多 `$0.50`，只有一个时可用满 `$1`。否则“其余不变”会把 W3 风险翻倍，破坏与 W2 的配对比较。V1 可继续作诊断，不再参与晋升。

### 9.4 F-4 — ACCEPT

阶段 A 预注册四个候选族：M0 为现行 `mu/sigma/SIGMA_MULT` 高斯对照；M1 加 `station x lead` 偏差校正，`b_hat` 夹在 `±3F`、`sigma_hat` 地板 `1.2F`；M2 为分层经验残差和既定 shrink 阶梯；M3 为 M1 加固定 `nu=4` 的 Student-t 尾。四族共用 F-1 修正后的规则解析和 event-level 积分；M0 比较的是旧分布假设，不复制 T-high bug 或逐桶 floor 造成的概率不守恒。

选择只用逐日 rolling-origin 的 out-of-fold 结果，以 city-day 为聚类单元，CRPS 为主指标、log loss 为副指标；候选清单、排序规则和训练截止时刻在阶段 A 首次评分前冻结。若独立 city-days 少于 100，M2 只有在预注册排序上胜过 M1 和 M3 时才可入选，不能因设计偏好胜出。阶段 A 胜者冻结为 `W3_MODEL_V1`，阶段 B 不再换族。

### 9.5 F-5 — ACCEPT

公开 `GET /markets/trades` 复核到 `taker_outcome_side`、`yes_price_dollars`、`count_fp`、`created_time` 和 `trade_id`。对假想 YES maker bid，`taker_outcome_side == "no"` 表示对手主动买 NO；若其 YES 等价成交价至少穿过我方 limit 一档，可以形成更硬的成交反事实。

F2 分为 `F2_print` 和 `F2b_book`。`F2_print` 要求 intent 后、TTL 内出现去重后的打印，且 `taker_outcome_side == "no"`、`yes_price_ticks <= maker_limit_ticks - 1`；`F2b_book` 保留后续 ask 严格低于 limit，或缺少可靠 taker 方向时的原逐笔穿价加量证据。两者并集进入主 P&L，但必须分列 n、P&L 和 CI；同一 intent 同时命中时以 `F2_print` 为证据标签。反事实 fill price 一律按较保守的 maker limit 计，不用穿价打印美化成交价。`quote_updates.fill_evidence` 取 `{F2_print, F2b_book}`。

### 9.6 F-6 — ACCEPT

`report_shadow()` 常设 `PT_null` 反事实行，不设正式交易臂，也不进入晋升门。口径冻结为：每个 ticker 只取 tau 窗内首次 `mid_yes < 0.15` 的全桶 snapshot，以当时 `yes_ask + taker fee` 买一张并持有到结算；不看 `q_met/q_trade`，重复扫描不重复买。报告 total、每张均值、city-day block CI、样本漏斗，并附 `print != fill`。这能直接检验纯价格尾部是否仍有收益，不需要新增采集字段。

### 9.7 F-7 — ACCEPT

`quotes` 是全桶快照，不是候选子集。每次 run 记录 7 个配置 KXHIGH series 中全部 active、双边报价存在的桶，不受 `<15c`、`.15-.40`、模型门或选择结果过滤，并保存 `series/event_key/settlement_local_date/tau_h`。这样 PT null、`.15-.40` fade 反事实和 W2 配对都能从同一机会集复算；`opportunities` 才承载 candidate/eligible/selected 状态。

### 9.8 F-8 — ACCEPT

maker limit 向下量化后若 `< yes_bid`，记录 `eligible_unpostable`，不创建 intent；该状态只进入漏斗和概率诊断。`maker_limit == yes_bid` 是合法 join，`maker_limit == yes_bid + tick` 是改善一档，两者都使用相同 strict trade-through 证据，不假设队列位置。所有比较用整数 tick，避免 deci-cent 浮点边界误判。

### 9.9 修订 JSON 增量

以下采用 JSON Merge Patch 语义；`null` 表示删除旧键，只列相对 §8 JSON 的改动键。

```json
{
  "challenger": {
    "tau_hours": [2, 48],
    "tau_layers": ["(2,8]", "(8,20]", "(20,48]"],
    "intent_ttl_end_tau_h": 2,
    "market_rule_semantics": {
      "canonical_fields": ["yes_sub_title", "rules_primary"],
      "ticker_role": "cross_check_only",
      "threshold_mismatch_action": "skip_market"
    },
    "bucket_parity_oracle": ["B", "T_low"],
    "stage_a_model_selection": {
      "families": ["M0", "M1", "M2", "M3"],
      "primary": "rolling_origin_oof_CRPS",
      "secondary": "rolling_origin_oof_log_loss",
      "cluster_unit": "city_day",
      "M2_strict_win_required_below_independent_city_days": 100
    },
    "primary_fill": "F2_print_or_F2b_book",
    "fill_evidence_values": ["F2_print", "F2b_book"],
    "quote_scope": "all_active_two_sided_buckets_in_7_KXHIGH_series_each_run",
    "PT_null_diagnostic": {
      "candidate": "first_snapshot_mid_yes_lt_0.15_per_ticker",
      "entry": "yes_ask_plus_taker_fee",
      "size_contracts": 1,
      "gate_role": "diagnostic_only",
      "warning": "print_not_fill"
    },
    "maker_limit_below_bid_state": "eligible_unpostable_no_intent",
    "maker_join_at_bid": true,
    "capacity_V2": {
      "trigger_day": 30,
      "projected_F2_at_90d_lt": 90,
      "strategy_version": "W3_NWS_TAIL_MAKER_V2",
      "selected_per_city_day_max": 2,
      "city_day_total_shadow_risk_usd": 1.0,
      "formal_counts": "restart_no_pooling_with_V1"
    }
  },
  "promotion_gate": {
    "settled_intents_min": null,
    "eligible_settled_tickers_min": 300,
    "F2_fills_min": 90,
    "each_tau_layer_F2_fills_min": 20,
    "tau_layer_negative_cumulative_pnl_veto": true,
    "paired_brier_population": "selected_plus_eligible_not_selected",
    "paired_brier_aggregation": "equal_weight_within_city_day_then_settlement_date_or_storm_block_bootstrap"
  }
}
```
