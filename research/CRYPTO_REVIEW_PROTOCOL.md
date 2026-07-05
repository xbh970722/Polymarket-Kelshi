# Crypto 亏损触发式复盘协议 (Fable 5 总领)

触发: quant_loop 在结算后检测到自上次复盘以来 crypto 结算亏损 ≥5 笔 或 累计亏损 ≥$1
(四币全算: KXBTC/KXETH/KXSOL/**KXXRP** — FABLE-C 修正, XRP 曾是盲区)。
执行机制 (2026-07-05 如实修正): quant_loop 只**举旗** (写 data/review_due_shortcycle.json;
favorites 回撤写 review_due_favorites.json, 双信箱防互相覆盖); **每 3 小时的监工任务**
发现旗子后执行复盘 (headless 直召被证不可靠已弃用)。最坏延迟 ~3 小时, 期间交易继续,
由全局 $5 日亏熔断兜底。

## 复盘会话必须完成的六步

1. **拉数据**: sqlite 查询 data/ledger.db 中 id > review_state.last_review_id 的全部 crypto
   结算交易 (前缀取自 config 的 shortcycle.series + favorites.series 并集, 当前 =
   KXBTC/KXETH/KXSOL/KXXRP, 含 15M), 以及 data/quant_loop.log 相关段落。
2. **找模式, 不数尸体**: 亏损单共享什么结构?哪个门放行的?(滞后门/确定区/基差守卫/
   窗口上限/预算) 与 SHORTCYCLE_DESIGN.md 中在检验的假设 (H1-H4...) 逐条对照 —
   哪条被数据支持, 哪条被证伪。区分实力与运气: q=0.8 输一笔是噪声, 同构输五笔是偏差。
3. **裁决** (三选一, 必须选):
   - 参数调整: 收紧/放宽某个门 (写明 旧值→新值→数据依据);
   - 结构调整: 新增/删除某条规则 (在 shortcycle.py / pipeline.py 实施);
   - 死刑: 触发 SHORTCYCLE_DESIGN.md 的废通道红线 → 在 config 将对应 series 移出,
     PushNotification 告知用户。
4. **实施**: 改 config/代码, `python -m py_compile` 验证, 更新 SHORTCYCLE_DESIGN.md
   复盘编号章节 (Review #N: 数据→诊断→裁决→新假设)。
5. **记账**: 更新 data/review_state.json: {"last_review_id": <本次覆盖到的最大id>,
   "ts": <ISO时间>, "review_no": N}; 删除 **data/review_due_shortcycle.json**
   (R3-FABLE 修正: 旧名 review_due.json 已拆分, 删错名字会让监工每 3h 重复复盘)。
6. **归档**: git add -A && git commit -m "crypto review #N: <一句话裁决>" && git push。

## 通道分流 (读 review_due_*.json 的 "lane" 字段)

- `lane` 缺省或非 favorites → **短周期策略复盘** (原六步, 针对 shortcycle/15m)。
- `lane == "favorites"` → **热门收割回撤复盘** (2026-07-03 用户设定的节拍器):
  1. 拉 data/ledger.db 中 title LIKE 'favorite%' 的全部结算交易, 算命中率、
     平均买入价、亏损集中在哪个价带/币种/方向。
  2. 对照假设: favorite-longshot bias 是否在 Kalshi crypto 成立?亏损是"热门真不便宜"
     还是"价带选错/单侧押注/踏空集中"?查 data/market_calibration.db 的热门桶最新偏差。
  3. **调整并继续** (不是停用): 三选一 —— 收窄价带 (如 [0.85,0.95]→[0.88,0.93])、
     调方向中性平衡、降单笔/日预算; 在 config.yaml `favorites:` 实施。**继续下单是默认。**
  4. 记账: data/fav_review_state.json 已由通道写入 steps_reviewed; 你只需在
     SHORTCYCLE_DESIGN.md 追加 "Favorites Review #N: 数据→诊断→调整"。
  5. 删除**你处理的那个文件** (favorites 复盘删 data/review_due_favorites.json;
     短周期复盘删 data/review_due_shortcycle.json), commit+push。
  - 仅当 hard_stop_steps ($15) 触及时才建议真正停用, 并 PushNotification 用户。

## 权限边界 (硬约束)

- 复盘**可以**: 调整策略参数/门槛/规则、收紧预算、停用某 series、废除通道。
- 复盘**不可以**: 提高任何美元上限 (单笔/日预算/敞口/熔断) —— 那是用户专属权力;
  不可以动 ensemble/weather/swing 的参数 (只管 crypto 短周期); 不可以改 VALUES.md 数值。
- 静默完成 (GitHub 即记录); 仅"死刑裁决"或改动失败时 PushNotification。
