# R11 红方设计刺杀报告 — RED-X2

**席位**: RED-X2（R11 红方设计刺客）  
**审计时点**: 2026-07-09 17:23 MDT  
**纪律**: 只读审计；未下单；未运行 `tests/`；未调用 git；唯一写入为本报告。  
**总裁决**: **NO-GO。阵地 D 的“连续两刻”不是驻留时间，而是调度器抽签；穿越直通道把刚被否决的单条件 hair trigger 原样装回。阵地 C/H16 的采样例外没有法源，阵地 H 又把若干复活门锁在只有实盘才能产生的数据上。**

## 证据边界

工作区在审计开始及交付前均不存在题面指定的 `r11_blue_position.md` 和任何 `r10_red_*.md`。因此，下文不能假装做了蓝方原文逐句勘误；“蓝方声明”只指题面明确列出的阵地 D、C、H、H16 及“h15 停挂 / elevated 不开仓”等主张。可复核证据来自：

- `research/SHORTCYCLE_DESIGN.md`
- `research/GAP245_ARCHITECTURE.md`
- `config.yaml`
- `src/pipeline.py`、`src/h10.py`、`src/wxfade.py`
- `scripts/quant_loop.py`、`data/quant_loop.log`
- `data/ledger.db`、`data/stop_shadow.db`、`data/h10_shadow.db`、`data/wxfade_shadow.db`
- `D:\kalshi-ticks\ticks_20260705.db` 至 `ticks_20260709.db`
- Coinbase Exchange 官方 `/ticker`、`/candles` 公共端点

缺失蓝方原件本身是一项审计阻断：任何声称“蓝方已写明例外、重置口径或状态定义”的答辩，必须先补原文，不能靠事后口述补法。

## RX2-01 — CRITICAL：阵地 D 的“两刻驻留”保护是计数器，不是时间约束

蓝方把“连续两刻”当作防抖，但 `quant_loop` 的“刻”没有固定长度。目标分钟由 `MARKS` 与 `LIGHT_MARKS` 混排，间隔本来就是 2、3、4 分钟，再叠加每刻 8–52 秒 jitter（`scripts/quant_loop.py:20-27, 350-364`）。轻刻在守卫前串行跑 h15、h10；整刻先跑 settle、h15 才到守卫（同文件 `367-370, 381-390`）。超时或全刻余下任务拖延还会让循环跳过后续目标分钟。

我用 `data/quant_loop.log` 中每次 h15 子命令完成时刻作为守卫调用代理：整刻守卫紧跟 h15，轻刻只隔一个 h10。截止 17:23，共得到 289 个相邻间隔。

| 口径 | 均值 | 标准差 | CV | 最短 | 最长 |
|---|---:|---:|---:|---:|---:|
| 剔除一次循环重启空档 | 171.3s | 47.7s | 0.279 | **18s** | 235s |
| 含 16:17→17:20 重启空档 | 183.9s | 218.6s | 1.189 | **18s** | **3,804s** |

18 秒不是偶然噪声，而是稳定的整点重复执行。整刻余务跨到下一小时后，调度器走 `else`，先安排下小时 `:00:20`；该轻刻很快结束后，它重新枚举 `LIGHT_MARKS`，又发现带 jitter 的正常 `:00` 尚在未来，于是同一目标分钟再跑一次。03:00、04:00……16:00 均出现约 18 秒双刻（`quant_loop.py:350-361`；日志例：03:00:21、03:00:39）。

所以：

- 从首次合格样本到第二次样本，所谓驻留实测为 **18–235 秒**，相差 13 倍。
- 从真实条件开始到开火，还要加上“等到首次采样”的相位误差；连续运行下可接近 0–470 秒，循环重启时可超过一小时。
- “漏一刻是否重置”“REST 失败算阴性还是缺失”“两个重复 :00 是否算两刻”均无定义。

这不是保护带，而是把风险阈值交给调度负载。D 只有改成单调时钟上的 `dwell_ms`、规定最大样本龄并把缺失样本与阴性样本分开，才配叫驻留。

## RX2-02 — CRITICAL：穿越直通道就是单条件 hair trigger；本地已经有假穿越尸体

现行开火逻辑是：先要求 held-side bid ≤ 0.70；随后只要 `losing OR near` 就立即下退出单（`src/pipeline.py:1273-1275, 1321-1342`）。蓝方若只给“贴线”支路加两刻驻留，却让“穿越”直通，最危险的支路仍是一笔 Coinbase REST `/ticker` 价格决定生死。

Coinbase 官方把 `/ticker` 定义为“last trade (tick)、best bid/ask 和 24h volume 的快照”。代码却只读 `.json()["price"]`，不校验响应中的 `time`、`trade_id`、bid/ask、状态码、价格范围或第二来源（`pipeline.py:1293-1297`）。换言之，一笔末笔成交、旧响应或异常值都能成为直通开火票。

官方口径与复核入口：[`Get product ticker`](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-ticker)、[`Get product candles`](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles)。K 线值按官方 `[time, low, high, open, close, volume]` 顺序解析；原始查询均使用 `granularity=60` 和表内 UTC 时段，例如 #607 为 `SOL-USD/candles?granularity=60&start=2026-07-09T03:32:00Z&end=2026-07-09T04:02:00Z`。

我把 `stop_shadow.db`、`ledger.db`、本地逐秒 Kalshi tick 与 Coinbase 官方 1 分钟 K 线对齐，找到以下已发生的假穿越：

| trade | 触发与现货证据 | 守卫动作 | 随后发生什么 |
|---|---|---|---|
| **#607 KXSOLD-26JUL0900-T76.9999，持 YES** | 2026-07-09 03:41Z，REST 读到 **76.99 < 76.9999**。该分钟 Coinbase O/H/L/C = **77.02/77.08/76.99/77.05**：只有下影穿线，开收都在线上。 | YES 从 90c 在 53c 退出，账面 -$1.18。 | 到期端本地 YES bid = **0.99**。这是字面意义的“瞬时插针开火”。 |
| **#391 KXETH15M-26JUL070800-00，持 YES** | 2026-07-07 11:53Z，REST 1776.94 < strike 1777.64；11:53 K 线 O/H/L/C = 1778.40/1778.40/1776.70/1776.84。 | 以 37c 退出。 | 11:54 收回 1777.80；到期端 YES bid = **0.999**。反穿持续不足两分钟。 |
| **#526 KXETH15M-26JUL081030-30，持 NO** | 2026-07-08 14:23Z，REST 1736.00 > strike 1735.41；14:23 K 线 O/H/L/C = 1736.91/1738.38/1735.17/1735.49。 | NO 从 84c 在 43c 退出，账面 -$1.28。 | 14:24 收到 1734.48；到期端 NO bid = **0.999**。 |
| **#646 KXBTCD-26JUL0910-T62999.99，持 NO** | 日志明确写 `spot losing`。13:53Z K 线全分钟在线上：O/H/L/C = 63055.15/63199.00/63000.05/63038.01。 | NO 从 88c 在 23c 退出，账面 -$0.67。 | 13:54 收回 62963.71，14:00 到期端 NO bid = **0.99**。即使不是单 tick 错读，一分钟穿越仍足以误杀。 |

聚合结果同样难看：58 次有完整到期端 tick 的 stopguard 出场里，28 次持仓侧最终 bid ≥0.90，29 次 ≤0.10，1 次居中。更窄地看，14 个“首次触线时现货已经穿越”的样本中，**4 个最终持仓侧 bid ≥0.90，假穿越代理率 28.6%**。这不是完整止损效用评估，终盘 bid 也不是正式结算字段；但它足以否决“穿越天然可靠，可以绕过驻留”的主张。

更致命的是，蓝方承诺的复盘仪器根本不存在。`stop_shadow.db.stops` 只有 `trade_id/ticker/ts/held_bid/entry_price/contracts/spot/strike`，以 `trade_id` 为主键；没有 `fired`、原因、退出价、后续样本或正式结果。代码只在首次 bid≤0.70 时插一行（`pipeline.py:1249-1257, 1299-1305`）。`SHORTCYCLE_DESIGN.md:425-426` 所称“fired 与否都留痕、周末校准假触发率”并未落地。

## RX2-03 — HIGH：C-C 没有“门内采样非部署”例外；H16 要么违法扩枝，要么拿真钱伪装影子

C-C 原文很硬：在 h15 过 20 笔门或 h10 某门/止损条款裁决前，“不再扩 15m 任何新枝”，并列举无 SOL-h15、无 BTC 复活、无 kill-switch 建造（`SHORTCYCLE_DESIGN.md:319-323`）。原文没有“只登记新假说、只跑定向分析、只做门内采样便不算扩枝”的例外。

H16 恰恰是一个新 15m maker 变体，有独立 L*=0.86、GO/KILL、币×家族分层和新 ledger title（同文件 `378-398`）。同一文档记载 H16 出现时 h15 仅 11/20。把现有通用 tick 被动落盘称为“没部署”尚可；以它注册新分支、选择新阈值并准备新实盘 title，已经扩了研究树。蓝方是在裁决后发明例外，不是在执行 C-C。

而且现有数据并不能自动过 H16 门。逐日 tick 库的 `book` 表只有盘口、L2/L3、末笔价与序号；没有 strike、Coinbase spot、z、close_time 或官方 result。源码中也没有 H16 扫描器/评分器。文档自己承认 settlement/result 列仍是施工缺口。所谓“被动积累到量即可裁决”至少还缺一次离线拼接和官方结算接入。

20 笔门则形成二选一悖论：

- 若沿用 h15 历史队列门，当前 h15 已有 47 笔 settled/closed，20 笔早已越过；蓝方不应再拿它当等待条件。
- 若 H16 或新体制要求新的 20 笔真实 maker 成交，h15“停挂”后不会再产生样本。为了攒样本而挂“试单”就是部署：GTC 会占用真余额，能被成交，且当前每单最多 x3、约 $2.53。`pipeline.py:2450-2458` 也明确把 pending h15 订单计作交易所现金预留。

用 quote touch 代替真实成交，违反 `print≠fill`；用真挂单测队列，又违反“全停挂/纯研究态”。两边不能同时为真。

## RX2-04 — CRITICAL：阵地 H 的“研究态”没有统一活性语义，部分门是永久冻土

| 门 | 必需数据 | 生产者 | 全影子状态下是否继续 | 红方判决 |
|---|---|---|---|---|
| D 假触发率/驻留校准 | live 持仓、每次 bid/spot/strike、是否 fired、终局 | `cmd_stopshadow` | **否**。无 live 持仓就无事件；有持仓也只记首次触线。 | 永久冻土。 |
| h15 20 笔队列门 / H16 前 20 笔实成 KILL | 真实 GTC 排队与成交 | h15 live maker | **否**。停新挂后只有存量单可能成交，随后归零。 | 永久冻土；“试单”会打破全影子。 |
| H16 quote GO | Kalshi tick + Coinbase/strike/z + 官方结算 | 外部 ws_capture + 尚不存在的 scorer | tick 继续，裁决字段与程序不继续。 | 原料在长，证据链不长；人工冻土。 |
| H13 final6 n150 | τ≤6 的真实 ask 与官方 result | `h10.scan/settle` | `series_live: []` 时**会**继续；若把“研究态”实现成 `mode: paper`、`live.enabled:false` 或 `h10.enabled:false`，`cmd_h10` 会在 scan 前 return。 | 活性取决于未定义的状态实现。当前 46/150。 |
| h10 复活/再裁决 | τ>6 shadow ask 与官方 result | `h10.scan/settle` | 同 H13。当前 `series_live: []` 仍采；真 paper mode 则全停。 | 当前 n=510、均值 -1.8c，已经 KILL，不是“尚待研究”。 |
| W2 n60 | Kalshi weather book + 官方 result | `wxfade.scan/settle` | 会。scan 在 live gate 之前，小时任务仍跑。 | 不死锁；但当前 n=81、均值 -4.6c，已经 ARCHIVE。 |
| vol/macro 解冻 | Coinbase 24h RV / UTC 时间窗 | `_vol_regime` / `_in_macro_window` | 会。 | 可自动解冻，不是研究门。 |

所以“研究态是不是永久冻土”的答案不是简单的是或否：**D、h15 新成交门和 H16 实成门是；H13/h10/W2 只有在保留全局 live 模式、保留命令调用、仅清空各自 live 列表时才活。** 蓝方若把“全影子”写成一个口号而不写状态机，运维者只要合理地切到 `paper`，H13 与 h10 也会一起冻死。

还有一处隐蔽污染：H13 与 h10 main 共用 `h10_shadow.shadow`，且 `ticker` 是主键。一个 BTC ticker 若先在 τ>6 命中 main 并插入，τ≤6 时 H13 的 `INSERT OR IGNORE` 不会再记录。H13 并非独立仪器，只是同一张“首次命中拥有样本”表按 `tau_min` 事后切片（`src/h10.py:54-108, 139-180`）。

## RX2-05 — CRITICAL：阵地书、config 与代码多处不是同一个系统

| 声明/现行状态 | config + 代码实况 | 判定 |
|---|---|---|
| D 已有“两刻驻留” | `losing or near` 同一次调用立即退出；没有 dwell 状态。 | **未实现** |
| stop shadow 会保存 fired/未 fired 并校准假触发 | 表中无 fired、原因、序列或 result；每个 trade 只存首次触线。 | **未实现** |
| h15 在 elevated/storm “不开仓” | 代码只在没有 resting row 时检查 regime。已有 GTC 在 regime/macro 切换后仍继续 resting，成交即新增暴露（`pipeline.py:1522-1635`）。 | **只阻止新下单，不阻止新成交** |
| h15 HARD STOP / MTM halt 已停挂 | 两个检查也位于 `if resting: return` 之后；旧 GTC 不会因硬停或 MTM 越线被撤。 | **部分实现** |
| elevated 全体不开仓 | h15 阻止新挂；favorites 若启用只降到 x1；h10 没有 vol gate；shortcycle 也没有 vol gate。 | **广义声明为假** |
| h15 当前已停 | `config.yaml:307` 仍 `enabled:true`，缓存 regime=calm；17:20 又挂出 #684，17:23 成交。 | **事实为假** |
| h10 实盘探针已停 | `series_live: []`，shadow/H13 继续。 | **已实现** |
| favorites 已停且粘性 | `favorites.enabled:false`，命令入口先 return。 | **已实现** |
| H16 已在采可裁决证据 | 无 H16 源码；tick schema 缺 z/strike/result；只有研究文档。 | **未实现** |
| h10 慢 GO 已提高到 +4c | GAP-245 立法写 +4c；`src/h10.py` 仍以 n≥300、均值 **+2c** 报 SLOW-GO，config 注释也仍写 +2c。 | **未实现** |
| H13 GO 已提高到 +2.4c | 立法写 +2.4c；代码 n≥150 时仍用 **+1c** 且 loss≤1。 | **未实现** |
| W2 GO 已提高到 +13.7c | 立法写 +13.7c；`src/wxfade.py` 仍以 **+3c** 报 USER-DECISION。 | **未实现** |
| W2 shadow 是最终裁判，ARCHIVE 会停通道 | 当前 shadow 已报 ARCHIVE；`wxfade_live.enabled:true`，`cmd_wxfade` 不读取 gate 判决，仍可下真钱单。 | **裁判无执行权** |
| h15 的 exchange expiry 是崩溃保险 | config 仍这样写；研究法典说 demo 证实 130s 后仍 resting；代码一处说“不被 honor”，另一处又说 demo-gym 已证明自动取消（`pipeline.py:1717-1721, 1810-1813`）。 | **权威状态互相矛盾** |

最严重的不是某一行阈值落后，而是“研究门”和“执行门”没有绑定：h10/W2 可以在报告里 KILL/ARCHIVE，执行层却只看独立 config 开关。蓝方所谓阵地 H 不是状态机，只是一组可互相打架的布尔量。

## 红方封锁条件

在下列条件同时满足前，阵地 D/H16 不得判 GO：

1. 用单调时间定义驻留，不再用“刻数”；写清最小/最大样本龄、缺失样本语义和循环重启恢复规则。
2. 穿越与贴线走同一套多样本确认；若保留直通，至少需要 Coinbase `time/trade_id/bid/ask` 新鲜度校验及第二来源/分钟收盘确认，并用上述四个假穿越做回放门。
3. stop shadow 逐观测保存 `reason/fired/spot_ts/order_result/final_result`，能直接计算 false-trigger 和 missed-save，不能再靠事后拼三库。
4. 明确“全影子”的机器状态：不得用 `mode: paper` 意外掐死 h10/H13；逐门写 producer、cadence、unlock owner 和最大等待期。
5. H16 必须先解决 C-C 法源与数据 schema；任何“试单挂档”都按 live deployment 和真实资金风险记账。
6. 把 GAP-245 的 h10/H13/W2 新阈值写进唯一可执行 gate，并让 KILL/ARCHIVE 粘性阻断 live；尤其先处理已经 ARCHIVE 但仍 live-enabled 的 W2。

**最终刺杀结论**: 蓝方用“连续两刻”给贴线支路披上防抖外衣，却让穿越支路继续一票开枪；再用“门内采样”给冻结令开了原文没有的洞。其研究态既不能保证继续产证，也不能保证真的停风险。D 与 H16 均应退回设计台，H 阵地不得宣称闭环。

{"seat":"RED-X2","hits":[{"id":"RX2-01","severity":"CRITICAL","hit":"连续两刻的确认间隔实测18-235秒，循环重启可达3804秒；驻留保护由调度负载抽签"},{"id":"RX2-02","severity":"CRITICAL","hit":"穿越直通道复活单条件hair trigger；14个首次穿越样本中4个最终持仓侧bid>=0.90"},{"id":"RX2-03","severity":"HIGH","hit":"C-C原文无门内采样例外；H16新增15m分支与冻结令冲突"},{"id":"RX2-04","severity":"HIGH","hit":"h15停挂后20笔真实maker门无法积累；试单挂档会占真资金并可成交"},{"id":"RX2-05","severity":"CRITICAL","hit":"全影子态下D校准、h15/H16实成门永久冻土，h10/H13活性又依赖未定义的live状态"},{"id":"RX2-06","severity":"HIGH","hit":"stop_shadow只存每个trade首次触线，无fired、连续样本或终局，无法兑现假触发率校准"},{"id":"RX2-07","severity":"CRITICAL","hit":"h15只阻止新下GTC，不会在elevated/macro/hard-stop/MTM切换时撤旧单，旧单仍能开新暴露"},{"id":"RX2-08","severity":"CRITICAL","hit":"h10慢GO、H13 GO、W2 GO仍执行旧阈值+2c/+1c/+3c，未落实立法+4c/+2.4c/+13.7c"},{"id":"RX2-09","severity":"CRITICAL","hit":"W2影子已ARCHIVE但live仍enabled，裁决结果不阻断下单路径"},{"id":"RX2-10","severity":"HIGH","hit":"H16无实现且tick schema缺z、strike与官方result，所谓可裁决的被动采样尚不存在"}]}
