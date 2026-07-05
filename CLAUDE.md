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
