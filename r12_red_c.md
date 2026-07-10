# R12 决胜轮红方 C 席审计

席位：R12-RED-C  
审计时间：2026-07-09（America/Denver）  
约束：只读代码与配置；`ledger.db` 以 SQLite URI `mode=ro` 打开；未下单，未运行 `tests/`，未调用 Git。

## 总裁决

**HIT。两处 CONFIRMED 击穿。**

第一处打 FREEZE-14 的执行传播链。冻结令只写在当前 Claude 会话的临时 scratchpad；实际会改门的三小时监工没有收到它，反而仍收到“Implement changes”的旧命令。仓库协议也仍要求监工在复盘时立即改 config/代码。所谓“所有改动进提案队列”没有文件、状态字段、写入口或消费入口。

第二处打 v3 声称的冻结“当前态”。ensemble 既没有锁成一张/最低美元，也没有实现“半仓持有到结算”。当前只读账本已有一笔 `x9` ensemble 仓，代码仍给整仓设置 swing target/stop，并在命中时卖掉整仓。条件满足时，所谓 `$2.50` 帽还会被 high-conviction 路径抬到 `$4.00`。

## 14 天内会自主改变交易行为的机制清单

这里区分“按已冻结规则运行”和“AI 自主改规则”。前者不自动构成违令；后者才直接击穿 FREEZE-14。

| 机制 | 14 天内的动作 | 当前活性 | FREEZE-14 文义是否覆盖 | 执行层是否覆盖 | 裁决 |
|---|---|---:|---|---|---|
| `review_due_shortcycle.json` 亏损复盘 | 亏损达到 5 笔或 `$1` 后举旗；三小时监工可收紧、放宽、增删规则或删 series | 条件活跃：`crypto_review.enabled=true`，shortcycle live | **是**。这正是“入场门/尺寸/所有参数改动” | **否**。监工和协议仍命令立即实施 | **CONFIRMED 击穿** |
| favorites 复盘 | 每 `$3` 回撤写旗并“ADJUST then continue” | 当前 `enabled=false`，无新动作面 | 是 | 旧监工仍可处理已有旗，但当前无旗 | 当前未触发，不单列命中 |
| h10 `consec_loss_stop` | 连输 N 笔写 `h10_stop_*.json`，单币转影子 | 代码存在，且旧 `KXSOL15M` 停牌文件仍在；但 `series_live=[]` | 不属于改参数，是既定停牌状态机 | 不需要额外冻结；实盘面已关闭 | **未中** |
| h15/h10 硬回撤停牌 | 累计亏损到线后停止开仓并写 review flag | h15 当前已过线；`review_due_h15maker.json` 在场 | 属硬安全方向，可合理算刹车 | 停牌生效；但 h15 邮箱未接入监工清单 | 刹车本身未中；邮箱脱节是治理缺口 |
| `daily_loss_halt` / `_mtm_halt` | 已实现或已实现+浮亏触线后拒绝所有新仓；MTM 快照失明且有开仓时也 fail-closed | 活跃 | **明确豁免** | 已实现 | **未中** |
| STOPGUARD FIRE | 每个 mark 检查 `bid<=0.70` 且现货穿越/贴线，条件满足即卖仓 | 活跃；quant loop 的 light/full mark 都调用 | v3 逐项明说 FIRE 维持单刻现状 | 已实现 | **未中**。这是冻结规则内的既定执行，不是改门 |
| `_vol_regime` | 最多每 10 分钟切 calm/elevated/storm；切换 favorites 开仓、h15 开仓和 FIRE 贴线阈值 | favorites 已停、h15 已硬停；仍可影响未来 shortcycle 仓的 FIRE 阈值 | v3 明说“regime 油门维持已修态” | 已实现 | **未中**。活作用面只剩守卫阈值；不能硬说成 AI 调参 |
| swing `manage` + 五日重判 | 每小时/每次 daily cycle 按 target/stop 卖整仓；到期后无头 ensemble 可改 target 或退出 | **活跃**；4 笔当前 ensemble swing 仓的 review date 均落在 14 天窗内 | stop 可争辩为安全刹车；take-profit、抬 target 和整仓退出不在例外内 | **没有冻结闸** | 与下文 ensemble 当前态一起构成 **CONFIRMED 击穿** |

关键代码：

- `scripts/quant_loop.py:367-370,381-407` 在 light/full mark 调 h15、h10、STOPGUARD，并约每小时调用 `manage`。
- `src/pipeline.py:364-397` 实现 MTM 熔断；`src/engine.py:107-117` 实现日亏及敞口硬限额。
- `src/pipeline.py:1236-1415` 实现 FIRE；`src/pipeline.py:1322-1328` 根据 regime 把贴线阈值在 `0.05%/0.075%/0.10%` 三档切换。
- `src/pipeline.py:311-361` 的 regime 分类器使用 10 分钟缓存。favorites 在 `src/pipeline.py:745-751` 受它控制，h15 在 `src/pipeline.py:1629-1635` 受它控制。
- `config.yaml:291` 已把 h10 `series_live` 设为空，所以连续亏损停币当前没有新的真钱作用面。

## 攻击 R12-C1：FREEZE-14 没有进入会改参的无头会话

**打哪条**

打蓝方 v3 `r11_blue_position_v3.md:74-78` 的核心承诺：“AI 14 天不得自主更改”“所有参数改动一律进提案队列”。同时打 `:87-88` 的结论：“真钱车道从此进 14 天预注册窗”。

**代码、配置与实际会话证据**

1. 三小时监工仍明确要求立即改参。

   `C:\Users\xuboh\.claude\scheduled-tasks\kalshi-shortcycle\SKILL.md:3` 标明每三小时运行；`:11` 要求发现 shortcycle/favorites/legacy 旗子后：

   > Implement changes, py_compile verify ... delete the processed review_due file, commit ... and push.

   它的唯一硬边界是“不提高美元帽”，没有 FREEZE-14、14 天截止时间或提案队列。

2. 它调用的正式协议仍强制三选一并落地。

   `research/CRYPTO_REVIEW_PROTOCOL.md:18-24` 要求在“参数调整/结构调整/死刑”中必须选一，并改 config/代码；`:55-57` 明确授权调整门槛、规则、预算和 series。协议既允许**放宽**门，也允许新增规则，不能用“降低风险是硬刹车”替它开脱。

3. 仓库顶层契约与 FREEZE-14 正面冲突。

   `CLAUDE.md:3-7` 要求所有定时/无头会话全自动，有推荐就直接执行，并称降额、停通道、急刹“永远可以直接做”。`FREEZE-14` 没写入 `CLAUDE.md`、`config.yaml`、`.claude/`、`src/`、`scripts/` 或复盘协议。对这些运行文件执行精确搜索，`FREEZE-14` 为零命中；`proposal_queue`、`freeze_until`、`frozen_until` 和“提案队列”也为零命中。

   仓库确有两条更老、更窄的冻结文字：`research/SHORTCYCLE_DESIGN.md:319-323` 只冻结 15m 新枝，`research/WEATHER_LANES.md:48-49` 只冻结天气参数。它们没有覆盖 hourly shortcycle 复盘、ensemble target 或本轮统一 FREEZE-14。

4. 这不是一份无人运行的旧任务。

   实际会话转录 `C:\Users\xuboh\.claude\projects\D--Polymarket-Kelshi\c707907b-f7bc-480d-9feb-b7975c04cbed.jsonl:1` 记录 2026-07-09 15:21 UTC 的自动 `kalshi-shortcycle` 会话。首条上下文明确写着“user is not present”“execute autonomously”，随后只注入该 scheduled-task 文件。它与保存 v3 的 `acd916af-...` 会话不是同一会话。

5. 触发链仍在线。

   `config.yaml:192-197` 保持 `crypto_review.enabled=true`，阈值为 5 笔或 `$1`；`scripts/quant_loop.py:242-270` 达线后写 `review_due_shortcycle.json`。因此只要 14 天内 shortcycle 达线，监工收到的可执行命令就是“立即改”，不是“排队等待”。

6. “提案队列”甚至没有一个兼容现有邮箱的入口。

   当前 `data/review_due_h15maker.json:1` 已存在，内容是 `{"lane":"h15maker","realized":-4.56,...}`。正式协议 `research/CRYPTO_REVIEW_PROTOCOL.md:32-37` 声称会处理 h10/h15 邮箱，但监工 `SKILL.md:11` 只检查 shortcycle、favorites 和 legacy 三个固定文件，漏掉 h10、h15、weather。这个现存 h15 flag 不会被该任务消费。它既没进“提案队列”，也没进旧复盘执行队列。

7. `kalshi-daily-cycle` 还有第二条绕行。

   `C:\Users\xuboh\.claude\scheduled-tasks\kalshi-daily-cycle\SKILL.md:3,8-16` 每天 9:00/15:00 启动独立 live ensemble 会话。它确实**不处理 crypto review flag**，这一点不硬造；但它调用的 `.claude/skills/trade-cycle/SKILL.md:15-22` 要求对 `REVIEW-DUE` 持仓重新仲裁，并允许“raise target”或直接退出。target 改动属于 v3 所说的“所有参数改动”，又不是日亏/单笔帽/余额兜底。

   实际自动会话 `C:\Users\xuboh\.claude\projects\D--Polymarket-Kelshi\219f142f-6888-4c47-9e34-fc3bba625ef5.jsonl:1` 证明这条 daily task 也在独立上下文中运行。

**杀伤评级：击穿（CONFIRMED）**

FREEZE-14 目前是一句只约束写它的会话的宣言，不是系统约束。触发器、权限文件、监工任务和实际无头会话组成了一条完整的旁路。蓝方不能用“AI 应该记得”防守，因为未来任务收到的上下文已由转录证明；其中没有 v3 scratchpad。

**蓝方必答**

1. 哪个持久化对象记录 freeze start/end、冻结字段集合和提案？请给路径、schema 与消费代码。
2. 下一次 `review_due_shortcycle.json` 出现时，`kalshi-shortcycle` 在哪一行从“Implement changes”改成“只写提案”？
3. 为什么 `CLAUDE.md:7` 的“降额/停通道永远可以直接做”不会覆盖掉 FREEZE-14？优先级由谁执行？
4. h15/weather/h10 邮箱由哪个任务消费？当前 `review_due_h15maker.json` 为什么不在监工清单？

## 攻击 R12-C2：ensemble 的“最小额 + 半仓结算”是未实现的当前态

**打哪条**

打 v3 `r11_blue_position_v3.md:60-67` 的三项事实声明：ensemble `$2.50` 帽维持、改半仓持有到结算、三模型源保持最小额 live。也打 `:82-83` 把这些写成冻结起点的“当前态”。

**代码与只读 DB 证据**

1. 没有“一张样本模式”。

   `src/engine.py:46-66` 按 bankroll × 1/3 Kelly 算 stake，再用 `int(stake // price)` 决定张数。`src/pipeline.py:62-128` 的 ensemble decide 路径直接采用该张数，没有 `max_contracts=1`、sample mode 或 lane-specific 最小额开关。

   `config.yaml:85` 的 `$2.50` 只是单笔上限，不是“一张”。更直接的是 `config.yaml:102-106` 还保留 `$4.00` high-conviction 帽；`src/pipeline.py:103-108,140-156` 条件满足时把 effective cap 抬到 `$4.00`。所以“ensemble `$2.50` 帽维持”也不是硬不变量。

2. 只读账本已经给出反例。

   查询方式：

   ```python
   sqlite3.connect("file:D:/Polymarket-Kelshi/data/ledger.db?mode=ro", uri=True)
   ```

   当前 open live ensemble 行：

   | id | title（缩写） | price | contracts | cost | exit_type | target | stop | review_after |
   |---:|---|---:|---:|---:|---|---:|---:|---|
   | 154 | World Cup attendance | 0.88 | 2 | $1.77 | swing | 0.9160 | 0.4400 | 2026-07-10 |
   | 454 | Maine Senate nominee | 0.49 | 5 | $2.54 | swing | 0.6805 | 0.2450 | 2026-07-12 |
   | 571 | FOMC 0bps | 0.21 | 3 | $0.66 | swing | 0.2460 | 0.1050 | 2026-07-13 |
   | 659 | FOMC +25bps | 0.15 | **9** | **$1.43** | swing | 0.2055 | 0.0750 | 2026-07-14 |

   id 659 用九张而不是一张；一张 15c 合约才是这里的最低美元样本。四笔 review date 全在 FREEZE-14 内。

3. “半仓持有到结算”没有代码表示。

   `config.yaml:76-81` 仍为 `swing.enabled=true`。每笔 ensemble 入场后，`src/pipeline.py:128,159-167` 给**整行**分配一个 target/stop；`src/engine.py:78-95` 生成 swing plan。账本没有 `hold_contracts`、`swing_contracts` 或 half-lot 字段。

   命中 target/stop 后，`src/pipeline.py:194-207` 把 `t["contracts"]` 整数全部传给 `place_exit`；`:243-259` 按实际整单成交关闭。没有 `ceil(n/2)`、拆成两行或保留一半的分支。`scripts/quant_loop.py:405-407` 约每小时调用它，独立 `kalshi-swing-manage` 任务还会每三小时再调一次。

4. 这会直接破坏 v3 自己给半仓修复的理由。

   v3 `:60` 已承认 swing 止盈不产 Brier 结算样本。当前实现仍可能在结算前卖掉**全部** ensemble contracts。故“ensemble 是持续产 Brier 的样本源”在代码实际态中不成立；冻结 14 天只会把未修复状态继续运行。

**杀伤评级：击穿（CONFIRMED）**

这不是“最小额”的语义争论。数据库有 x9 反例，代码有 `$4` 条件帽和整仓退出路径，schema 里没有半仓保留表示。v3 宣称已经冻结的起点不存在。

**蓝方必答**

1. “最小额”对应哪个可执行旋钮？若是 `$2.50 cap`，请解释为什么 id 659 是 x9，以及为什么 high-conviction 能到 `$4`。
2. 半仓由哪个字段保存？整仓 `place_exit(t["contracts"])` 后，哪一半仍能等到结算？
3. FREEZE-14 是从未实现半仓修复之前开始，还是修复之后开始？若要先改代码，冻结起始时间记录在哪里？
4. 7 月 10、12、13、14 日到期的四笔 ensemble 重判，daily task 可以抬 target。它们进提案队列的代码在哪里？

## 当前态逐条核对

| v3 声称 | 配置/代码/DB 实际 | 裁决 |
|---|---|---|
| favorites `enabled=false` | `config.yaml:203` 为 false；`cmd_favorites` 立即 return | 相符 |
| h10 探针停 | `config.yaml:291` 的 `series_live=[]` | 相符 |
| h15 停 | config 仍 `enabled=true`，但累计实现为 -$4.56，`cmd_h15` 在 `src/pipeline.py:1637-1650` 硬停；due 文件已写 | 行为上相符，表达依赖动态 PnL 而非冻结开关 |
| shortcycle live 最小额 | enabled=true；`$1` 帽但 `max_contracts=5`，无一张锁。近期成交恰为 x1 | live 相符；“最小额不变量”未实现，重创但不另算击穿 |
| ensemble live 最小额 | Kelly 动态张数；当前 id 659 为 x9；条件帽可到 `$4` | **不符** |
| ensemble 半仓到结算 | 整行 swing，整仓退出 | **不符** |
| weather live 最小额 | W1 enabled=true、`$0.50` 帽、`max_contracts=3`；当前 W1 id 657 为 x1/$0.40 | live 相符；同样没有一张硬锁，不单独判击穿 |
| FIRE 单刻、regime 已修态 | FIRE 与三档 regime 都在线；未见驻留计数 | 相符 |
| 所有改动进提案队列 | 没有队列实现；监工仍直接改 | **不符** |

## 红方收口

我不把 MTM、日亏熔断、FIRE 正常卖仓或 regime 运行硬凑成违令。它们分别属于明示安全例外或 v3 明示保留的固定状态机。真正致命的是两件可复核的事实：会改门的 AI 任务没有收到冻结令；蓝方要冻结的 ensemble 当前态也没有落到代码和账本。

{"seat":"R12-RED-C","verdict":"HIT","hits":["R12-C1 CONFIRMED: FREEZE-14未传播到无头改参链且无提案队列","R12-C2 CONFIRMED: ensemble最小额与半仓持有到结算均未实现"]}
