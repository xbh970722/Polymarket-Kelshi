# 会话行为契约 (用户 2026-07-05: "所有session都auto")

1. **全自动**: 一切会话 (交互/定时任务/无头) 不因等用户输入而阻塞。有推荐项的
   决策直接按推荐执行, 并把"替用户拍了什么板"写进日志与晨报; 无推荐项时选
   保守路径继续。绝不在无头会话里调用交互式提问。
2. **用户专属杠杆 (AI 永不代行)**: 提高任何美元上限、恢复预算、充值决策。
   降低风险的动作 (降额/停通道/急刹) 永远可以直接做。
3. **编制**: Fable 5 定 goal/架构/API 契约/库选型并冻结 (蓝图:
   research/GAP245_ARCHITECTURE.md); codex/opus 席按 spec 施工与红队。
4. **凭据**: D:\kalshi-secrets\ (生产 key_id.txt + kalshi_test.pem; demo
   demo_key_id.txt + kalshi_demo.pem)。密钥永不回显/入库/进内存文件。
5. **实弹纪律** (research/VALUES.md 5f): tests/ 是实弹炮组, 永不进 pytest;
   炮组只打 demo (KalshiLive(demo=True)); 打生产须逐次说明且只读。
   改 config.yaml 后必须立刻冒烟受影响的 pipeline 子命令 (KeyError 是运行时的)。
6. **证据分级**: demo=D 类 (机制, 永不喂优势门); print 口径必须附
   "print≠fill" 警告; 晋升走预注册门 + 跨体制复现 (SHORTCYCLE_DESIGN.md)。
7. 实盘循环 (scripts/quant_loop.py, data/quant_loop.pid) 常驻 — 改它的代码
   要重启它; 改 src/pipeline.py 不用 (子进程逐刻加载)。
8. **崩溃自愈** (2026-07-05 死机后加): scripts/watchdog.ps1 -Loop 每 180s
   自查, 挂了就拉起 quant_loop + ws_capture (两者都自锁, 重复拉起无害)。
   开机自启走 HKCU\...\Run 的 "KalshiWatchdog" (无需管理员; 系统计划任务
   注册需提权, 故走 Run 键)。tick 采集器常驻脚本在 D:\kalshi-ticks\ws_capture.py
   (仓库外稳定路径), 数据写 D:\kalshi-ticks\ (非仓库, ~14GB/天, 事件驱动
   重写待施工)。查活: D:\kalshi-ticks\watchdog.log + 三进程 census。
9. **FREEZE-14 变更管控** (2026-07-09, R10-R12红蓝对攻+策略会全票的终局; 治
   "5天改12次门=主动管理净亏$19.72"的病)。**到 2026-07-23 (及后续边界日
   08-06/08-20), 任何会话——含每小时监工、每日循环、无头定时任务——对交易门/
   尺寸/zone/z_floor/止损/体制参数的自主变更一律禁止。** 允许的自主动作仅四类:
   ① 硬安全刹车 (日亏熔断/单笔帽/-$3回撤停/余额兜底/守卫按现有规则开火);
   ② 布尔关闭 (enabled: true→false); ③ 整数降尺寸 (max_contracts 只减不增);
   ④ 记提案 (追加 data/change_proposals.jsonl, 不改 config)。
   **数值收紧也算改门** (如 zone 收窄/门槛提高/z_floor 上调) → 进提案队列, 不即改。
   亏损复盘触发器 (crypto_review) 的裁决权被夺: 监工发现 review_due 只许输出
   HOLD / 记提案, **不许改任何 config 数值**。边界日由一个 Fable 会话按
   research/FREEZE14_ADJUDICATION.md 的预注册判据表一次性裁决整个队列 (三列格式:
   预注册判据|窗口观测值|裁决是否可推导), 表外动作=协议违规记入9/1档案。
   此条覆盖并暂时凌驾第1条"有推荐直接执行"于交易参数上——冻结期"推荐"=记提案。
   加钱/加杠杆/恢复预算/恢复停用通道/改验收标准 仍是第2条用户专属, 不受冻结影响
   (用户随时可拉)。冻结到期或用户明令即解除。
