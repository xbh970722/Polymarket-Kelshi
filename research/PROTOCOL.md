# 研究协议 (Research Protocol)

每轮交易循环中,Claude Code(下称"我")按此协议对候选市场做研究。
**这份文件是纪律,不是建议。任何一步偷懒都会污染校准数据。**

## 分工

| 角色 | 职责 |
|---|---|
| 情报 | agent-reach / web-access 抓一手信息源 |
| 估计者 A | 我 (Claude) 独立估 P(YES) |
| 估计者 B | Codex (gpt-5.5, xhigh) 独立估 P(YES) |
| 裁决 | `src/engine.py` 用共识概率算净优势, 硬风控放行才成交 |
| 元决策 | 用户: 定领域、定风控、审报告、决定是否开真钱闸门 |

## 每个市场的研究步骤

### 0. 读规则 (必须第一步)
```
python -m src.pipeline rules TICKER
```
把 `rules_primary` 逐字读完。预测市场的坑一半在结算条款:
数据来源是哪家、截止时间是何时区、修订值算不算、平局怎么判。
**对"事件会不会发生"估得再准,搞错结算条款照样亏钱。**

### 1. 情报收集 (agent-reach / web-access)
按领域找一手来源,记录每条信息的时间戳:
- 经济数据: BLS/BEA 官方日历、FRED、CME FedWatch、近期联储官员讲话、机构 nowcast (Cleveland Fed / Atlanta GDPNow)
- 政治/地缘: 官方公告、主流通讯社 (AP/Reuters)、聚合民调、当事方原话
- 加密/科技/文娱: 现货价格与波动率、官方公告、行业媒体

规则: 优先一手来源;二手转述必须溯源;记下"市场还不知道什么"。

### 2. 盲估 (防锚定, 顺序不可颠倒)
- **先不看市场价**,我基于情报独立写下 P(YES) 和三条核心理由。
- 同时让 Codex 盲估(prompt 里不给市场价、不给我的估计):

```
codex exec --skip-git-repo-check -s read-only "You are an independent superforecaster. Do not search for prediction-market prices; estimate from evidence only.

MARKET RULES (verbatim): <rules_primary>
CLOSE TIME: <close_time>
INTEL DIGEST (each item timestamped): <intel>

Task: estimate P(YES). Think adversarially about base rates, current evidence, and time remaining. Output STRICT JSON only:
{\"p_yes\": 0.XX, \"ci_low\": 0.XX, \"ci_high\": 0.XX, \"key_drivers\": [\"...\"], \"what_would_change_mind\": [\"...\"]}"
```

### 3. 对辩 (第二轮)
把「我的估计+理由」和「市场当前价」发给 Codex,要求它:
攻击我的最弱论据 -> 说明它更新/不更新的理由 -> 给最终 p_yes。
我读它的攻击,同样更新我的最终估计。
**更新要有新论据,不许因为"它比我低"就无脑向中间靠。**

### 3.5 验证层 (下单前强制, 2026-07-03 起)

任何将产生**交易指令**的市场(跳过的不需要),在 decide 之前必须过验证:
- **社媒**: agent-reach 搜 Twitter / Reddit 近 24h 该事件关键词 —— 找模型没见过的突发信息
  (官员临时讲话、伤病/行程变更、链上异动、爆料)。
- **数据库**: 经济类查 FRED / BLS / 官方日历确认数据发布时点与最新值;
  加密类查交易所现货与资金费率; 政治类查官方公告原文。
- 发现重大新信息 → 带着新证据回炉第二轮, 重新出家族终值再 decide。
- 验证动作与结论写进 research JSON 的 sources / rationale。

### 4. 落盘
写入 `reports/research_<YYYY-MM-DD>.json`:
```json
{
  "date": "2026-07-03",
  "items": [
    {
      "ticker": "KX...",
      "title": "...",
      "q_claude": 0.62,
      "q_codex": 0.58,
      "rationale": "三句话: 核心论据 / 主要风险 / 双方分歧点",
      "sources": ["url1", "url2"]
    }
  ]
}
```
然后 `python -m src.pipeline decide --research <该文件>` —— 引擎决定,不是我决定。

## 集成模式 (2026-07-03 起为标准配置)

用户定调: **2×Opus 4.8 + 2×Codex (xhigh) 盲估, Fable 5 仲裁**。

- 四个盲估者 = 2 个模型家族 × 2 种方法论人格 (INSIDE VIEW 机制建模 / OUTSIDE VIEW 基率锚定)。
  同一份情报摘要, 全程不给任何预测市场价格。每个估计者一次评完本轮全部市场。
- **模型全部来自 config.yaml `ensemble:` 段** — Claude 家族用 Agent tool
  (model 参数 = `claude_family.model`, 禁用工具), Codex 家族用
  `codex exec -m <codex_family.model> -c model_reasoning_effort=<effort>` 后台并行。
  换代升级 (Opus 5.0 / Codex 5.6 / Fable 下一代) 只改配置, 协议与代码不动。
  仲裁者按 `arbiter_preference` 顺序: 有 Fable 额度用 Fable 5, 用尽切 Opus 4.8。
- 聚合规则 (预注册, 不看结果调整): `q_claude` = Opus 家族均值, `q_codex` = Codex 家族均值。
- 仲裁者 (Fable 5) 职责: 预注册各市场合理区间; 检查家族内分歧 (>0.10 标记人工复核);
  识别哪个市场存在"决定交易与否的 crux"; 只对这类市场发起第二轮聚焦对辩
  (每家族一个代表, 揭示市场价作为证据); 汇总落盘。
  **仲裁者永远不用自己的数字替换估计者的输出** —— 它可以杀掉一笔交易 (风险裁决),
  不能创造一笔交易。
- 第二轮后家族最终值直接作为 q_claude / q_codex 进引擎。
- 成本意识: 每轮 4-6 次 LLM 调用。估计聚类紧密且无优势的市场不辩第二轮。

## 铁律

1. **盲估先于看价**。看过市场价再估的数字作废。
2. 双模型分歧 > 0.10 -> 引擎自动跳过,写进报告标记人工复核。这不是失败,这是系统在工作。
3. 我不修改 config.yaml 的 risk / live_gate 数值。调整限额是用户的决定。
4. 结算条款没读懂的市场,跳过,不硬估。
5. 每轮循环必须跑 settle + report,即使没有新交易——校准数据是整个系统的目的。
