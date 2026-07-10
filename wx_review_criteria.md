# W3 天气条件尾部影子组验收标准

适用规格：`wx_impl_spec.md`  
验收对象：`W3_NWS_TAIL_MAKER_V1` / `W3_GATE_V1`  
验收角色：Opus 提交实现与证据；Sonnet 独立复算；WX-DIRECTOR 裁决  
本验收只能批准影子采集，不能批准 wire、真钱或提高风险。

## 1. 裁决枚举

- `APPROVE_SHADOW_ONLY`：全部 CRITICAL/HIGH 通过，MEDIUM 无影响证据链的遗留；仅允许手动或另批批准的影子采集。
- `REQUEST_CHANGES`：存在可修复的 CRITICAL/HIGH，或证据不足以复算。
- `REJECT_SCOPE`：实现出现下单、认证、live wire、修改现有风险门、自动晋升或污染既有 DB。

任何 CRITICAL 失败都不得条件通过。验收人必须实际复算 fixture/临时库，不能只读代码后打勾。

## 2. 提交包最低要求

提交者必须提供：

1. 完整 diff 和文件清单。
2. schema version、migration 说明和一份空库 schema dump。
3. 模型 manifest 示例，含数据/code/config/rules/fee hash 与 RNG seed。
4. fixture 来源、去敏说明和期望结果。
5. 本文件第 11 节命令的原始输出。
6. 所有网络 endpoint 与 HTTP method 清单。
7. 默认 `data/wxtail_shadow.db` 未被 smoke 写入的证明。
8. `src/weather.py`、`src/wxfade.py`、`src/pipeline.py`、`scripts/quant_loop.py`、`config.yaml` 零 diff 的证明。
9. 已知限制；禁止用“后续补”掩盖会改变 q、fill、P&L 或 gate population 的缺口。

## 3. 范围与安全

| ID | 级别 | 验收项 | 通过标准 |
|---|---|---|---|
| WX-SCOPE-01 | CRITICAL | 独立模块 | 新逻辑位于 `src/wxtail.py`；未扩写 W1/W2/live-loaded 文件。 |
| WX-SCOPE-02 | CRITICAL | 无实盘能力 | 无 `KalshiLive` import、无订单/取消订单 endpoint、无认证 header、无账户/余额读取。静态搜索和运行 trace 都通过。 |
| WX-SCOPE-03 | CRITICAL | 凭据隔离 | 不访问 `D:\kalshi-secrets`；日志、fixture、DB 无 key/token。 |
| WX-SCOPE-04 | CRITICAL | CLI fail closed | `--live` 或未知交易参数非零退出；网络 trace 中只有公开 GET。 |
| WX-SCOPE-05 | CRITICAL | 不 wire | 未改 pipeline、quant loop、watchdog、autostart、现有 config；无 import side effect 启动采集。 |
| WX-SCOPE-06 | HIGH | 故障隔离 | W3 网络/DB/解析失败只返回 W3 error report，不影响现有进程或 DB。 |
| WX-SCOPE-07 | HIGH | 只读 comparator | W2 DB 用 URI `mode=ro` + `PRAGMA query_only=ON`；尝试写入应失败。 |
| WX-SCOPE-08 | CRITICAL | 无自动晋升 | gate 通过只输出 proposal 状态；不得改 config、调度或下单。 |

## 4. 市场、站点与时间语义

| ID | 级别 | 验收项 | 通过标准 |
|---|---|---|---|
| WX-RULE-01 | CRITICAL | 结构化 strike 主语义 | payout 集合只由 `strike_type/floor_strike/cap_strike` 构造；subtitle/rules/ticker 只核验。 |
| WX-RULE-02 | CRITICAL | T-high off-by-one | fixture `T94`, subtitle `95° or above`, `greater`, floor 94：`H=94` 为 NO，`H=95` 为 YES。 |
| WX-RULE-03 | CRITICAL | T-low | fixture `T87`, subtitle `86° or below`, `less`, cap 87：`H=86` 为 YES，`H=87` 为 NO。 |
| WX-RULE-04 | CRITICAL | between inclusive | floor 93/cap 94：93、94 为 YES；92、95 为 NO。 |
| WX-RULE-05 | CRITICAL | event partition | overlap、gap、冲突或未知 strike type 令整 event `ineligible_rules`；完整 event 概率和误差 `<=1e-12`。 |
| WX-RULE-06 | HIGH | ticker 不掌权 | 构造 ticker 与结构化字段冲突 fixture；实现必须跳过，不能按 ticker 继续。 |
| WX-STN-01 | CRITICAL | exact station | series settlement source、contract terms、rules 与 CITIES station 四方核验；任一冲突 fail closed。 |
| WX-STN-02 | HIGH | 规则修订 | rules/terms/source hash 改变会创建 event revision 并暂停 eligibility，不覆盖旧 revision。 |
| WX-TIME-01 | CRITICAL | LST 窗口 | NYC 夏季 settlement date 的窗口为 `05:00Z` 到次日 `05:00Z`，不是 `04:00Z`；冬季仍是 `05:00Z`。 |
| WX-TIME-02 | CRITICAL | 其他 standard offset | Chicago/Austin 用 UTC-6、Denver UTC-7、LAX UTC-8、Miami/Philadelphia UTC-5，全年固定用于气候窗。 |
| WX-TIME-03 | HIGH | 半开区间 | 观测恰在 LST start 纳入，恰在 end 排除；forecast period 用 overlap 规则。 |
| WX-TIME-04 | HIGH | no future leak | artifact received time或 observation timestamp 晚于 decision time 时不可进入该 snapshot；fixture 必须能抓到泄漏。 |
| WX-TIME-05 | CRITICAL | 决策截止定义 | run 保存 start/decision/complete；decision 在必需 quote 收到后冻结，tau 按 decision 算，不能用 run start。 |
| WX-TIME-06 | HIGH | quote 新鲜度 | 最后 quote 距 decision 超过 30 秒时只采集、不 eligible。 |

## 5. 固定点价格、费用与尺寸

| ID | 级别 | 验收项 | 通过标准 |
|---|---|---|---|
| WX-PX-01 | CRITICAL | 无 binary float 决策 | 价格比较、tick、P&L 与费用使用 Decimal 或固定点整数；DB 保存整数单位。 |
| WX-PX-02 | CRITICAL | 动态网格 | 从 `price_ranges` 计算合法价；覆盖 1c、0.1c 及跨 band 边界 fixture。 |
| WX-PX-03 | CRITICAL | maker 性质 | 创建时满足 `bid <= limit < ask`；等于 bid 可 join；最高只改善一个当时合法 tick。 |
| WX-PX-04 | HIGH | 向下量化 | raw cap 落在非法价时取不高于 cap 的最大合法价；量化后低于 bid 记 `eligible_unpostable`。 |
| WX-PX-05 | CRITICAL | fee fail closed | series fee type/multiplier/scheduled change 缺失或未知时不入组；保存 fee source/hash。 |
| WX-PX-06 | HIGH | 保守 fee | 主口径 fee reserve 是适用 maker fee与同价同张 taker fee的较大者；maker 低费只作 sensitivity。 |
| WX-PX-07 | CRITICAL | 费用批量舍入 | fee 对整批 `C` 计算后再分摊；不得把“每张向上取整”误当批量费用。 |
| WX-PX-08 | CRITICAL | `$1` 风险单位 | `C*L+fee <= $1`，C 为正整数且为合法组合中的最大值。边界 fixture 精确通过/拒绝。 |
| WX-PX-09 | CRITICAL | 双 edge 门 | 每个 intent 同时满足净 edge `>=5pt` 和概率比 `>=1.50`；使用 `q_trade_lcb`。 |
| WX-PX-10 | CRITICAL | 必须有 NWS 增量 | `w>0` 且 `q_met_lcb>mid_yes`；构造 w=0、宽 spread fixture，必须只有 price/null candidate、没有 W3 intent。 |

## 6. 采集、schema 与幂等

| ID | 级别 | 验收项 | 通过标准 |
|---|---|---|---|
| WX-DATA-01 | CRITICAL | 采集先于策略门 | collect 在无账户、满帽、无 quote、价格不在带时仍保存 event/market/NWS metadata。 |
| WX-DATA-02 | HIGH | 全事件可审 | 每 run 保存全部 active markets；无双边 book 用 `quote_state` 表达，不静默丢弃。 |
| WX-DATA-03 | CRITICAL | 原始证据 | artifact 有请求/接收时间、URL/参数、sha256、原始内容；解析结果可回指 artifact。 |
| WX-DATA-04 | CRITICAL | append-only 结算 | 新结算或修订追加 revision；旧值保持可查。 |
| WX-DATA-05 | CRITICAL | 成交专表 | 每笔 public trade 保存唯一 trade_id、方向、YES 价、数量、block 标记、执行/首次看到时间。 |
| WX-DATA-06 | HIGH | 时间格式 | UTC 时间带 offset；settlement local date、LST start/end 单列。 |
| WX-DATA-07 | CRITICAL | 幂等 | 同 fixture 重跑两次：run 可新增，artifact 按 hash 去重；opportunity、intent、trade、settlement revision 不重复。 |
| WX-DATA-08 | HIGH | 事务恢复 | 在每个关键写入点注入异常；库保持可打开、无半条 intent/fill。 |
| WX-DATA-09 | HIGH | schema version | 新库可创建；未知未来 schema 明确拒绝，不能静默降级。 |
| WX-DATA-10 | CRITICAL | comparator 纯读 | report/adjudicate 不改变 W2 mtime、size 或内容 hash。 |

## 7. 模型与冻结

| ID | 级别 | 验收项 | 通过标准 |
|---|---|---|---|
| WX-MODEL-01 | CRITICAL | 正确 target | 训练 target 是结算 `H_cli`；METAR/forecast max 不能冒充 outcome。 |
| WX-MODEL-02 | CRITICAL | 四族固定 | M0–M3 与规格一致；M0 不复制 T-high bug或逐桶 floor。 |
| WX-MODEL-03 | CRITICAL | rolling origin | 每个 validation city-day 的训练数据严格早于它；同一 city-day 所有 snapshot 不拆分。 |
| WX-MODEL-04 | HIGH | 选择规则 | CRPS 主、log loss 副、并列选简单；少于 100 city-days 时 M2 必须严格胜 M1/M3。 |
| WX-MODEL-05 | CRITICAL | event PMF 守恒 | 每族输出非负 event-level PMF，总和为 1；不得逐桶独立 floor。 |
| WX-MODEL-06 | CRITICAL | 市场 shrink 无泄漏 | `w` 只由阶段 A OOF 固定网格选择；tie 取小 w；阶段 B 不更新。 |
| WX-MODEL-07 | CRITICAL | LCB 可复算 | `q_met_lcb/q_trade_lcb` 均由 2,000 次 city-day block bootstrap、固定 seed/indices生成；同 snapshot 重算 bit-for-bit 一致。 |
| WX-MODEL-08 | HIGH | LCB 标签诚实 | 报告称其为 selection stress bound，不称“已校准 90% 覆盖率”。 |
| WX-MODEL-09 | CRITICAL | manifest 完整 | 数据/code/config/parser/rules/fee hash、参数、w、seed、门槛、训练截止均存在。缺一不得开始 B。 |
| WX-MODEL-10 | CRITICAL | 版本重启 | 改变 q/candidate/limit/fill/settlement/gate population 会新开版本且 formal count 归零。 |

模型 fixture 必须包含一个“旧高斯看似大 edge、经验尾模型降级”的样本，以及一个市场 shrink 选择 `w=0` 的无增量样本。实现必须允许模型诚实地产生零机会，而不是强迫发单。

### storm/regime 验收

| ID | 级别 | 验收项 | 通过标准 |
|---|---|---|---|
| WX-REG-01 | CRITICAL | 触发集冻结 | 只按 alert allowlist、thunderstorm+PoP>=50%、3 小时温差>6F 三条触发；边界值 50% 通过、6F 不通过。 |
| WX-REG-02 | HIGH | heat 分离 | Heat Advisory/Excessive Heat Warning 只记 heat regime，不增加 storm n。 |
| WX-REG-03 | CRITICAL | 扫描时可见 | storm flag 只引用当时已发布 artifact；后发 alert 不得回填早期 snapshot。 |
| WX-REG-04 | CRITICAL | episode 无 outcome | union-find 只读 alert id、trigger type、series 与日期，不读 result/P&L；成员集 hash 可复算。 |
| WX-REG-05 | HIGH | episode append-only | 新日期使 episode 扩展时追加 assignment，不覆盖旧 assignment；gate 固定 as-of population。 |

## 8. 在线选择、intent 与取消

| ID | 级别 | 验收项 | 通过标准 |
|---|---|---|---|
| WX-SEL-01 | CRITICAL | tau 边界 | 三层严格为 `(2,8]`、`(8,20]`、`(20,48]`；2h 拒绝、8h 属第一层、20h 属第二层、48h 属第三层。 |
| WX-SEL-02 | CRITICAL | 决策层确定性 | 同 manifest/salt/city-day 永远分到同层；三层 fixture 均可命中。 |
| WX-SEL-03 | CRITICAL | 非分派层不发 intent | 仍采集/评分，但只能进诊断 population。 |
| WX-SEL-04 | CRITICAL | 因果选择 | 只从当前 run eligible 集选，不得结算后回看当天最大 edge。 |
| WX-SEL-05 | HIGH | tie-break | edge、limit、ticker tie-break 与规格一致，可复算。 |
| WX-SEL-06 | CRITICAL | 城市日风险 | V1 每 city-day 最多一个 intent；后续候选记 owned，不覆盖。 |
| WX-SEL-07 | CRITICAL | 每 ticker 一次 | 同 strategy/ticker 最多一个 formal intent；取消后不重发。 |
| WX-SEL-08 | CRITICAL | TTL | 6h、下一 forecast revision、tau=2h 三者取最早；边界测试通过。 |
| WX-SEL-09 | HIGH | 模型翻转取消 | refresh 首次发现跌破 all-in break-even 时取消；取消后的证据不能算 fill。 |

## 9. fill 反事实

| ID | 级别 | 验收项 | 通过标准 |
|---|---|---|---|
| WX-FILL-01 | CRITICAL | 严格时序 | 只接受 `intent.created < evidence <= cancel_or_expiry`；创建前、取消后、TTL 后均拒绝。 |
| WX-FILL-02 | CRITICAL | F2_print 方向 | 仅 `taker_outcome_side=no` 可证明假想 YES bid 被打；yes/unknown 方向拒绝。 |
| WX-FILL-03 | CRITICAL | strict trade-through | print YES 价必须低于 maker limit 至少一个当时合法 tick；等价只算 F1。 |
| WX-FILL-04 | CRITICAL | block trade 排除 | `is_block_trade=true` 永远不能形成 F2。 |
| WX-FILL-05 | CRITICAL | trade 去重 | 重复抓同 trade_id 不重复 fill 或 n。 |
| WX-FILL-06 | CRITICAL | F2b_book | 后续正尺寸 best YES ask 严格低于 limit 才通过；touch/空 size 为 F1。 |
| WX-FILL-07 | HIGH | 证据优先级 | 同时命中 print/book 时标 F2_print，只计一次。 |
| WX-FILL-08 | CRITICAL | 保守成交价 | 主 P&L 用 maker limit，不用更低穿价改善。 |
| WX-FILL-09 | CRITICAL | F0/F1 不进 P&L | 构造只有 touch 的全胜 fixture，主 n/P&L 仍为 0。 |
| WX-FILL-10 | HIGH | 证据可读 | proof_json 能单独说明为何通过，含 price grid、方向、时序和 source ids。 |

## 10. 结算、报告与预注册门

| ID | 级别 | 验收项 | 通过标准 |
|---|---|---|---|
| WX-SET-01 | CRITICAL | exact outcome | 只接收 exact ticker 的 settled/finalized YES/NO；不从价格或相邻桶推断。 |
| WX-SET-02 | CRITICAL | CLI cross-check | Kalshi expiration value与正确 station/date CLI 核验；冲突 quarantine，不进 gate。 |
| WX-SET-03 | CRITICAL | P&L 数学 | YES/NO、contracts、limit、保守 fee 的手算 fixture逐单位一致。 |
| WX-SET-04 | HIGH | 持有结算主口径 | 45c exit 单列 exploratory，不能改变主 P&L。 |
| WX-NULL-01 | HIGH | PT_null | first price-only snapshot、ask+taker fee、每 ticker一次；单列并标 `print != fill`。 |
| WX-NULL-02 | HIGH | PM_null | 不看 q，使用 price-only maker + F2；单列且不进入主 gate。 |
| WX-REP-01 | CRITICAL | 漏斗完整 | 报告 runs → observed → price candidates → eligible → selected → intents → F0/F1/F2 → settled；分城市/tau/storm。 |
| WX-REP-02 | CRITICAL | 证据标签 | F0/F1/PT/W2 的每个摘要都出现 `print != fill`；F2_print/F2b 分列。 |
| WX-REP-03 | HIGH | 当前未知可表达 | 零 F2 或样本不足时返回 `ACCUMULATE/UNKNOWN`，不能显示“edge survives”。 |
| WX-GATE-01 | CRITICAL | 样本定义 | unique ticker、eligible city-day、settlement date、F2、storm episode 的计数与规格完全一致。 |
| WX-GATE-02 | CRITICAL | 样本门全 AND | 任一最低值未达只可 ACCUMULATE；不得提前看 CI 晋升。 |
| WX-GATE-03 | CRITICAL | paired Brier population | 只用 first-eligible selected + eligible_not_selected；同 city-day 先等权。 |
| WX-GATE-04 | CRITICAL | P&L population | 只用 settled F2；按 max loss 归一并在 city-day 内按 risk 聚合。 |
| WX-GATE-05 | CRITICAL | block bootstrap | 10,000 次、固定 seed；先按 settlement date 成块，再合并跨日 storm episode 涉及的日期；percentile 95% CI 可复算。 |
| WX-GATE-06 | CRITICAL | 双 CI `>0` | 两个下界都严格大于 0 且累计 P&L>0 才可生成 proposal；等于 0 不过。 |
| WX-GATE-07 | CRITICAL | 分层否决 | 城市/tau 负 P&L、storm/nonstorm、CI 上界<=0、容量规则按规格执行；不得删样本重算。 |
| WX-GATE-08 | HIGH | W2 不冒充硬门 | W2 同期只读对照正常输出，但不因 print comparator 好/坏改变 V1 双 CI 裁决。 |
| WX-GATE-09 | CRITICAL | V1/V2 不 pooling | 容量 V2 有新版本、新时钟、新 population hash；V1 只留诊断。 |
| WX-GATE-10 | CRITICAL | 结果不可反向改门 | gate config/hash 与 manifest 一致；报告阶段没有调参入口。 |

### 必做 gate fixture

至少构造以下 6 组小型确定性库：

1. 样本不足但点估计全正：必须 `ACCUMULATE`。
2. P&L CI 下界正、Brier 下界负：`UNRELIABLE_MODEL_EDGE`。
3. Brier 下界正、P&L 下界负：`NO_EDGE_AFTER_EXECUTION`。
4. 两个下界恰为 0：不得通过。
5. 总组通过但一个达到 20 fills 的 tau 层累计负：不得通过。
6. Kalshi/CLI mismatch：被 quarantine 后，所有 gate n 相应减少。

## 11. 必跑验证命令

不得运行 `tests/` 或 pytest。验收至少运行：

```text
python -m py_compile src/wxtail.py scripts/wxtail_shadow.py scripts/wxtail_smoke.py
python scripts/wxtail_smoke.py --db <fresh-temp>/wxtail_smoke.db
python scripts/wxtail_smoke.py --db <same-temp>/wxtail_smoke.db
python scripts/wxtail_shadow.py --help
python scripts/wxtail_shadow.py --live
python scripts/wxtail_shadow.py collect --once --db <fresh-temp>/wxtail_public.db
python scripts/wxtail_shadow.py report --db <fresh-temp>/wxtail_public.db
python scripts/wxtail_shadow.py adjudicate --db <fresh-temp>/wxtail_public.db
```

期望：

- compile 全过。
- 两次 fixture smoke 的业务对象计数相同，只有允许的 run/audit 记录增加。
- `--live` 非零退出且没有网络写请求。
- 公开 smoke 只访问公开 Kalshi/NWS GET，写临时 DB。
- 新鲜公开库因未完成阶段 A/B 返回 `ACCUMULATE_STAGE_A` 或 `UNKNOWN`，绝不返回通过。

验收人另做静态搜索：

```text
rg -n "KalshiLive|create_order|cancel_order|D:\\\\kalshi-secrets|api-key|Authorization" src/wxtail.py scripts/wxtail_*.py
git diff -- src/weather.py src/wxfade.py src/pipeline.py scripts/quant_loop.py config.yaml
```

任何命中都要逐条解释；下单/认证/secret 命中默认 CRITICAL。

## 12. 通过后的唯一动作

`APPROVE_SHADOW_ONLY` 后只允许：

1. 保留冻结 manifest。
2. 以另批明确批准的只读调度积累阶段 A 数据，或手动运行影子命令。
3. 按固定节奏报告样本漏斗和 `UNKNOWN/ACCUMULATE`。

不得因为“实现验收通过”而宣称策略赚钱。盈利判断只来自阶段 B 预注册双 CI；真钱仍需新的架构 review、用户裁决与单独任务。
