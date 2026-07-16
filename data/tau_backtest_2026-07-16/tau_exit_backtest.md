# τ-出场预注册回测

**有效配对样本 n=4 / ledger 候选 387；SKIP=383；独立窗口簇=4。**

机械裁决：**FAIL**。样本与跳过数是裁决的一部分；不向缺档日期或不适用产品外推。

## 判据

| 预注册判据 | 观测值 | PASS/FAIL |
|---|---:|:---:|
| 满损笔数（亏损≥80%成本）下降 | baseline=0, policy=0 | FAIL |
| 最大回撤下降 | baseline=$0.00, policy=$0.17 | FAIL |
| 总 EV 差 bootstrap 95% CI 不显著为负 | Δ=$-0.68, CI=[$-1.1800, $-0.2800] | FAIL |

## 配对聚合

| 指标 | baseline 实际 | τ×贴线政策 | 差值 |
|---|---:|---:|---:|
| 总 P&L | $+0.58 | $-0.10 | $-0.68 |
| 满损笔数（亏损≥80%成本） | 0 | 0 | +0 |
| 最大已实现权益回撤 | $+0.00 | $+0.17 | $+0.17 |

总 EV 差采用按市场窗口簇配对 bootstrap（10,000 次，seed=20260712）；95% CI：[-1.18, -0.28]。

## 预注册开放格子：早期+贴线若扛到结算

条件恢复率：**2/2 = 100.0%**（恢复定义：持仓侧最终结算为赢）。
代理缺失而无法归类的仓位：0；终局未知：0。

## 2×2 政策（冻结）

| τ | 报价隐含贴线代理 | 动作 |
|---|---|---|
| 早期（τ>W/3） | 贴线 | 保留 0.6-capture；双条件止损照旧 |
| 早期（τ>W/3） | 远离 | 保留 0.6-capture；亏损侧穿越仍受双条件止损 |
| 晚期（τ≤W/3） | 贴线 | 下一 tick 全 taker 锁定 |
| 晚期（τ≤W/3） | 远离 | 撤 capture 目标，持有到结算；双条件止损仍优先 |

## 覆盖与跳过

可见 tick 日期：2026-07-11, 2026-07-12, 2026-07-13, 2026-07-14, 2026-07-16。
实际只读打开日期：2026-07-11。

| SKIP 原因 | 笔数 |
|---|---:|
| missing_tick_day | 277 |
| unsupported_policy_scope | 106 |

## 逐仓对照

| id | ticker | side | baseline P&L | policy P&L | EV差 | policy动作/格子 | 状态或SKIP原因 |
|---:|---|:---:|---:|---:|---:|---|---|
| 68 | KXBTCD-26JUL0503-T62799.99 | no | $+0.39 | — | — | — | missing_tick_day |
| 69 | KXSOLD-26JUL0503-T79.9999 | yes | $+0.19 | — | — | — | missing_tick_day |
| 70 | KXETHD-26JUL0503-T1769.99 | no | $+0.20 | — | — | — | missing_tick_day |
| 71 | KXXRPD-26JUL0503-T1.1399 | no | $+0.11 | — | — | — | missing_tick_day |
| 72 | KXETH15M-26JUL050245-45 | yes | $+0.09 | — | — | — | unsupported_policy_scope |
| 74 | KXXRPD-26JUL0504-T1.1399 | no | $+0.15 | — | — | — | missing_tick_day |
| 76 | KXBTCD-26JUL0504-T62799.99 | no | $-2.46 | — | — | — | missing_tick_day |
| 77 | KXETHD-26JUL0504-T1769.99 | no | $+0.20 | — | — | — | missing_tick_day |
| 81 | KXBTCD-26JUL0505-T62799.99 | yes | $+0.37 | — | — | — | missing_tick_day |
| 83 | KXXRPD-26JUL0505-T1.1399 | no | $+0.18 | — | — | — | missing_tick_day |
| 84 | KXETHD-26JUL0505-T1769.99 | no | $+0.39 | — | — | — | missing_tick_day |
| 85 | KXSOL15M-26JUL050445-45 | yes | $+0.12 | — | — | — | unsupported_policy_scope |
| 86 | KXHIGHPHIL-26JUL05-B91.5 | no | $+0.14 | — | — | — | unsupported_policy_scope |
| 87 | KXETHD-26JUL0506-T1769.99 | no | $+0.39 | — | — | — | missing_tick_day |
| 88 | KXBTCD-26JUL0506-T62699.99 | yes | $-2.69 | — | — | — | missing_tick_day |
| 89 | KXXRPD-26JUL0506-T1.1399 | no | $+0.10 | — | — | — | missing_tick_day |
| 90 | KXHIGHDEN-26JUL05-B93.5 | no | $+0.37 | — | — | — | unsupported_policy_scope |
| 92 | KXETH15M-26JUL050600-00 | yes | $+0.14 | — | — | — | unsupported_policy_scope |
| 97 | KXETHD-26JUL0507-T1749.99 | yes | $+1.19 | — | — | — | missing_tick_day |
| 93 | KXBTCD-26JUL0507-T62499.99 | yes | $+0.10 | — | — | — | missing_tick_day |
| 95 | KXSOLD-26JUL0507-T79.9999 | yes | $+0.28 | — | — | — | missing_tick_day |
| 98 | KXBTCD-26JUL0508-T62799.99 | no | $+0.13 | — | — | — | missing_tick_day |
| 100 | KXETH15M-26JUL050715-15 | yes | $+0.16 | — | — | — | unsupported_policy_scope |
| 102 | KXETH15M-26JUL050815-15 | no | $+0.16 | — | — | — | unsupported_policy_scope |
| 103 | KXETHD-26JUL0509-T1749.99 | yes | $+0.31 | — | — | — | missing_tick_day |
| 104 | KXBTCD-26JUL0509-T62699.99 | no | $-0.40 | — | — | — | missing_tick_day |
| 106 | KXSOLD-26JUL0509-T79.9999 | yes | $+0.11 | — | — | — | missing_tick_day |
| 108 | KXSOL15M-26JUL050845-45 | yes | $-0.83 | — | — | — | unsupported_policy_scope |
| 109 | KXBTCD-26JUL0510-T62799.99 | no | $+0.19 | — | — | — | missing_tick_day |
| 110 | KXETHD-26JUL0510-T1769.99 | no | $+0.45 | — | — | — | missing_tick_day |
| 111 | KXXRPD-26JUL0510-T1.1399 | no | $+0.12 | — | — | — | missing_tick_day |
| 114 | KXXRPD-26JUL0511-T1.1399 | no | $+0.10 | — | — | — | missing_tick_day |
| 115 | KXBTCD-26JUL0511-T62499.99 | yes | $+0.07 | — | — | — | missing_tick_day |
| 116 | KXETHD-26JUL0511-T1769.99 | no | $-2.58 | — | — | — | missing_tick_day |
| 117 | KXSOLD-26JUL0511-T80.9999 | yes | $+0.21 | — | — | — | missing_tick_day |
| 118 | KXSOL15M-26JUL051100-00 | no | $-0.87 | — | — | — | unsupported_policy_scope |
| 119 | KXETH15M-26JUL051115-15 | yes | $+0.16 | — | — | — | unsupported_policy_scope |
| 120 | KXSOLD-26JUL0512-T80.9999 | yes | $+0.19 | — | — | — | missing_tick_day |
| 121 | KXBTCD-26JUL0512-T62599.99 | yes | $+0.07 | — | — | — | missing_tick_day |
| 122 | KXHIGHMIA-26JUL05-B89.5 | yes | $-0.43 | — | — | — | unsupported_policy_scope |
| 123 | KXGPT-OPENB-26JUL10 | no | $-1.72 | — | — | — | unsupported_policy_scope |
| 124 | KXXRPD-26JUL0512-T1.1399 | no | $+0.07 | — | — | — | missing_tick_day |
| 126 | KXETHD-26JUL0512-T1769.99 | yes | $-1.11 | — | — | — | missing_tick_day |
| 127 | KXETH15M-26JUL051200-00 | yes | $+0.16 | — | — | — | unsupported_policy_scope |
| 129 | KXBTCD-26JUL0513-T62499.99 | yes | $+0.07 | — | — | — | missing_tick_day |
| 130 | KXXRPD-26JUL0513-T1.1399 | no | $+0.15 | — | — | — | missing_tick_day |
| 132 | KXETHD-26JUL0514-T1769.99 | yes | $+0.57 | — | — | — | missing_tick_day |
| 134 | KXXRPD-26JUL0514-T1.1399 | no | $+0.10 | — | — | — | missing_tick_day |
| 135 | KXBTCD-26JUL0514-T62499.99 | yes | $+0.08 | — | — | — | missing_tick_day |
| 139 | KXXRPD-26JUL0515-T1.1399 | no | $+0.14 | — | — | — | missing_tick_day |
| 140 | KXBTCD-26JUL0515-T62799.99 | no | $+0.10 | — | — | — | missing_tick_day |
| 141 | KXETHD-26JUL0515-T1769.99 | yes | $+0.20 | — | — | — | missing_tick_day |
| 143 | KXETH15M-26JUL051500-00 | yes | $+0.16 | — | — | — | unsupported_policy_scope |
| 144 | KXXRPD-26JUL0516-T1.1399 | no | $+0.09 | — | — | — | missing_tick_day |
| 145 | KXETHD-26JUL0516-T1789.99 | no | $+0.28 | — | — | — | missing_tick_day |
| 146 | KXBTCD-26JUL0516-T62599.99 | yes | $+0.07 | — | — | — | missing_tick_day |
| 148 | KXXRPD-26JUL0517-T1.1399 | no | $+0.10 | — | — | — | missing_tick_day |
| 149 | KXBTCD-26JUL0517-T62999.99 | no | $+0.10 | — | — | — | missing_tick_day |
| 150 | KXETH15M-26JUL051545-45 | yes | $+0.16 | — | — | — | unsupported_policy_scope |
| 151 | KXETHD-26JUL0517-T1789.99 | no | $+0.17 | — | — | — | missing_tick_day |
| 152 | KXETH15M-26JUL051630-30 | no | $+0.16 | — | — | — | unsupported_policy_scope |
| 153 | KXSOLD-26JUL0517-T80.9999 | no | $-0.14 | — | — | — | missing_tick_day |
| 154 | KXTRUMPATTEND | yes | $+0.06 | — | — | — | unsupported_policy_scope |
| 157 | KXBTCD-26JUL0519-T62699.99 | yes | $+0.15 | — | — | — | missing_tick_day |
| 158 | KXETHD-26JUL0519-T1769.99 | yes | $+0.22 | — | — | — | missing_tick_day |
| 159 | KXXRPD-26JUL0519-T1.1399 | yes | $+0.11 | — | — | — | missing_tick_day |
| 165 | KXBTCD-26JUL0520-T63399.99 | yes | $+0.09 | — | — | — | missing_tick_day |
| 166 | KXETH15M-26JUL051915-15 | yes | $+0.11 | — | — | — | unsupported_policy_scope |
| 168 | KXXRPD-26JUL0520-T1.1599 | yes | $-0.50 | — | — | — | missing_tick_day |
| 169 | KXETHD-26JUL0520-T1789.99 | yes | $-0.86 | — | — | — | missing_tick_day |
| 171 | KXSOLD-26JUL0520-T81.9999 | no | $+0.23 | — | — | — | missing_tick_day |
| 172 | KXXRPD-26JUL0520-T1.1599 | no | $+0.14 | — | — | — | missing_tick_day |
| 174 | KXETH15M-26JUL052000-00 | no | $+0.16 | — | — | — | unsupported_policy_scope |
| 176 | KXBTCD-26JUL0521-T63399.99 | yes | $-0.32 | — | — | — | missing_tick_day |
| 178 | KXETHD-26JUL0521-T1769.99 | yes | $+0.20 | — | — | — | missing_tick_day |
| 179 | KXXRPD-26JUL0521-T1.1799 | no | $+0.06 | — | — | — | missing_tick_day |
| 180 | KXSOLD-26JUL0521-T81.9999 | no | $-1.12 | — | — | — | missing_tick_day |
| 181 | KXBTCD-26JUL0521-T63599.99 | no | $-0.36 | — | — | — | missing_tick_day |
| 182 | KXBTCD-26JUL0521-T63499.99 | yes | $+0.08 | — | — | — | missing_tick_day |
| 183 | KXBTCD-26JUL0522-T63899.99 | no | $+0.16 | — | — | — | missing_tick_day |
| 189 | KXBTCD-26JUL0523-T63799.99 | no | $+0.08 | — | — | — | missing_tick_day |
| 191 | KXSOLD-26JUL0523-T81.9999 | no | $+0.11 | — | — | — | missing_tick_day |
| 192 | KXETHD-26JUL0523-T1789.99 | no | $+0.34 | — | — | — | missing_tick_day |
| 194 | KXETHD-26JUL0600-T1789.99 | no | $+0.42 | — | — | — | missing_tick_day |
| 195 | KXBTCD-26JUL0600-T63199.99 | yes | $-0.40 | — | — | — | missing_tick_day |
| 199 | KXBTCD-26JUL0600-T63299.99 | no | $+0.17 | — | — | — | missing_tick_day |
| 200 | KXSOLD-26JUL0600-T80.9999 | no | $+0.13 | — | — | — | missing_tick_day |
| 201 | KXETH15M-26JUL060015-15 | yes | $+0.16 | — | — | — | unsupported_policy_scope |
| 203 | KXBTCD-26JUL0601-T63099.99 | yes | $+0.10 | — | — | — | missing_tick_day |
| 204 | KXETHD-26JUL0601-T1789.99 | no | $+0.22 | — | — | — | missing_tick_day |
| 205 | KXXRPD-26JUL0601-T1.1399 | yes | $+0.07 | — | — | — | missing_tick_day |
| 206 | KXSOLD-26JUL0601-T80.9999 | no | $+0.32 | — | — | — | missing_tick_day |
| 207 | KXSOLD-26JUL0602-T80.9999 | no | $+0.19 | — | — | — | missing_tick_day |
| 208 | KXBTCD-26JUL0602-T63399.99 | no | $+0.08 | — | — | — | missing_tick_day |
| 210 | KXSOLD-26JUL0603-T79.9999 | yes | $+0.28 | — | — | — | missing_tick_day |
| 211 | KXBTCD-26JUL0603-T63299.99 | no | $+0.07 | — | — | — | missing_tick_day |
| 212 | KXXRPD-26JUL0603-T1.1399 | no | $+0.11 | — | — | — | missing_tick_day |
| 218 | KXBTCD-26JUL0604-T63099.99 | no | $+0.10 | — | — | — | missing_tick_day |
| 220 | KXSOLD-26JUL0604-T79.9999 | yes | $+0.11 | — | — | — | missing_tick_day |
| 221 | KXETH15M-26JUL060330-30 | yes | $+0.16 | — | — | — | unsupported_policy_scope |
| 222 | KXETH15M-26JUL060345-45 | yes | $+0.16 | — | — | — | unsupported_policy_scope |
| 224 | KXHIGHAUS-26JUL06-B98.5 | no | $-0.65 | — | — | — | unsupported_policy_scope |
| 225 | KXETHD-26JUL0604-T1769.99 | yes | $-0.49 | — | — | — | missing_tick_day |
| 227 | KXBTCD-26JUL0605-T63299.99 | no | $+0.18 | — | — | — | missing_tick_day |
| 229 | KXETH15M-26JUL060415-15 | yes | $+0.16 | — | — | — | unsupported_policy_scope |
| 231 | KXXRPD-26JUL0605-T1.1399 | yes | $-0.42 | — | — | — | missing_tick_day |
| 232 | KXETHD-26JUL0605-T1769.99 | no | $+0.31 | — | — | — | missing_tick_day |
| 234 | KXHIGHCHI-26JUL06-B78.5 | no | $+0.34 | — | — | — | unsupported_policy_scope |
| 235 | KXBTCD-26JUL0606-T62999.99 | no | $+0.11 | — | — | — | missing_tick_day |
| 237 | KXETHD-26JUL0606-T1769.99 | no | $+0.34 | — | — | — | missing_tick_day |
| 238 | KXSOLD-26JUL0606-T79.9999 | yes | $+0.17 | — | — | — | missing_tick_day |
| 242 | KXBTCD-26JUL0607-T62899.99 | no | $-0.47 | — | — | — | missing_tick_day |
| 243 | KXETHD-26JUL0607-T1769.99 | no | $-1.44 | — | — | — | missing_tick_day |
| 244 | KXSOLD-26JUL0607-T79.9999 | yes | $+0.24 | — | — | — | missing_tick_day |
| 251 | KXBTCD-26JUL0608-T62999.99 | no | $+0.13 | — | — | — | missing_tick_day |
| 252 | KXSOLD-26JUL0608-T80.9999 | no | $+0.28 | — | — | — | missing_tick_day |
| 253 | KXETH15M-26JUL060730-30 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 254 | KXETH15M-26JUL060745-45 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 256 | KXSOLD-26JUL0609-T78.9999 | yes | $+0.39 | — | — | — | missing_tick_day |
| 257 | KXBTCD-26JUL0609-T62299.99 | no | $+0.11 | — | — | — | missing_tick_day |
| 259 | KXETHD-26JUL0609-T1729.99 | yes | $+0.34 | — | — | — | missing_tick_day |
| 261 | KXETH15M-26JUL060900-00 | yes | $+0.04 | — | — | — | unsupported_policy_scope |
| 262 | KXBTCD-26JUL0610-T61899.99 | no | $-0.40 | — | — | — | missing_tick_day |
| 263 | KXETHD-26JUL0610-T1749.99 | no | $-1.21 | — | — | — | missing_tick_day |
| 264 | KXSOLD-26JUL0610-T79.9999 | no | $-1.30 | — | — | — | missing_tick_day |
| 265 | KXXRPD-26JUL0610-T1.0999 | yes | $+0.22 | — | — | — | missing_tick_day |
| 266 | KXETHD-26JUL0611-T1729.99 | yes | $+0.48 | — | — | — | missing_tick_day |
| 267 | KXBTCD-26JUL0611-T61299.99 | yes | $+0.12 | — | — | — | missing_tick_day |
| 268 | KXSOLD-26JUL0611-T80.9999 | no | $+0.17 | — | — | — | missing_tick_day |
| 270 | KXETH15M-26JUL061100-00 | no | $+0.13 | — | — | — | unsupported_policy_scope |
| 272 | KXBTCD-26JUL0612-T62599.99 | no | $-0.73 | — | — | — | missing_tick_day |
| 273 | KXSOLD-26JUL0612-T80.9999 | no | $-1.90 | — | — | — | missing_tick_day |
| 274 | KXETHD-26JUL0612-T1769.99 | no | $-1.83 | — | — | — | missing_tick_day |
| 275 | KXHIGHMIA-26JUL06-B89.5 | yes | $-0.35 | — | — | — | unsupported_policy_scope |
| 276 | KXLLM1-26JUL31-A | yes | $+0.09 | — | — | — | unsupported_policy_scope |
| 277 | KXBTCD-26JUL0612-T63099.99 | no | $-0.83 | — | — | — | missing_tick_day |
| 278 | KXBTCD-26JUL0613-T63899.99 | no | $+0.12 | — | — | — | missing_tick_day |
| 279 | KXETHD-26JUL0613-T1769.99 | yes | $+0.22 | — | — | — | missing_tick_day |
| 280 | KXSOLD-26JUL0613-T82.9999 | no | $+0.25 | — | — | — | missing_tick_day |
| 281 | KXXRPD-26JUL0613-T1.1599 | no | $+0.20 | — | — | — | missing_tick_day |
| 282 | KXETH15M-26JUL061245-45 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 283 | KXBTCD-26JUL0614-T64099.99 | no | $+0.12 | — | — | — | missing_tick_day |
| 284 | KXXRPD-26JUL0614-T1.1599 | no | $+0.15 | — | — | — | missing_tick_day |
| 287 | KXSOLD-26JUL0614-T81.9999 | no | $+0.17 | — | — | — | missing_tick_day |
| 288 | KXBTCD-26JUL0615-T63899.99 | no | $+0.15 | — | — | — | missing_tick_day |
| 289 | KXXRPD-26JUL0615-T1.1399 | yes | $+0.39 | — | — | — | missing_tick_day |
| 290 | KXSOLD-26JUL0615-T80.9999 | yes | $+0.22 | — | — | — | missing_tick_day |
| 294 | KXETH15M-26JUL061445-45 | yes | $+0.11 | — | — | — | unsupported_policy_scope |
| 295 | KXXRPD-26JUL0616-T1.1399 | yes | $+0.37 | — | — | — | missing_tick_day |
| 297 | KXBTCD-26JUL0616-T63899.99 | no | $+0.07 | — | — | — | missing_tick_day |
| 299 | KXETHD-26JUL0616-T1789.99 | yes | $+0.34 | — | — | — | missing_tick_day |
| 300 | KXBTCD-26JUL0617-T63499.99 | yes | $+0.15 | — | — | — | missing_tick_day |
| 302 | KXXRPD-26JUL0617-T1.1599 | no | $+0.17 | — | — | — | missing_tick_day |
| 303 | KXSOLD-26JUL0616-T81.9999 | no | $-1.25 | — | — | — | missing_tick_day |
| 307 | KXSOLD-26JUL0617-T81.9999 | no | $-1.76 | — | — | — | missing_tick_day |
| 309 | KXETHD-26JUL0617-T1789.99 | yes | $+0.34 | — | — | — | missing_tick_day |
| 310 | KXETH15M-26JUL061700-00 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 311 | KXBTCD-26JUL0618-T63599.99 | yes | $+0.14 | — | — | — | missing_tick_day |
| 313 | KXETHD-26JUL0618-T1849.99 | no | $+0.09 | — | — | — | missing_tick_day |
| 314 | KXSOLD-26JUL0618-T81.9999 | yes | $+0.25 | — | — | — | missing_tick_day |
| 315 | KXPLATNERDROPOUT-26-JUL8 | no | $+0.63 | — | — | — | unsupported_policy_scope |
| 316 | KXETH15M-26JUL061800-00 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 317 | KXBTCD-26JUL0619-T64599.99 | no | $+0.14 | — | — | — | missing_tick_day |
| 318 | KXSOLD-26JUL0619-T81.9999 | yes | $+0.17 | — | — | — | missing_tick_day |
| 319 | KXETH15M-26JUL061915-15 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 320 | KXSOLD-26JUL0620-T81.9999 | yes | $-1.20 | — | — | — | missing_tick_day |
| 322 | KXBTCD-26JUL0620-T63999.99 | yes | $-0.22 | — | — | — | missing_tick_day |
| 324 | KXETHD-26JUL0620-T1809.99 | no | $+0.39 | — | — | — | missing_tick_day |
| 325 | KXETHD-26JUL0621-T1789.99 | yes | $+0.31 | — | — | — | missing_tick_day |
| 326 | KXBTCD-26JUL0621-T63799.99 | yes | $+0.09 | — | — | — | missing_tick_day |
| 328 | KXETH15M-26JUL062030-30 | yes | $+0.07 | — | — | — | unsupported_policy_scope |
| 329 | KXSOLD-26JUL0621-T81.9999 | yes | $+0.45 | — | — | — | missing_tick_day |
| 331 | KXBTCD-26JUL0622-T63599.99 | yes | $+0.11 | — | — | — | missing_tick_day |
| 333 | KXBTCD-26JUL0623-T64099.99 | no | $+0.08 | — | — | — | missing_tick_day |
| 334 | KXSOLD-26JUL0623-T81.9999 | no | $+0.37 | — | — | — | missing_tick_day |
| 336 | KXETHD-26JUL0623-T1789.99 | no | $+0.34 | — | — | — | missing_tick_day |
| 337 | KXETH15M-26JUL062300-00 | no | $+0.12 | — | — | — | unsupported_policy_scope |
| 338 | KXSOLD-26JUL0700-T80.9999 | yes | $-0.85 | — | — | — | missing_tick_day |
| 339 | KXETHD-26JUL0700-T1769.99 | yes | $-1.39 | — | — | — | missing_tick_day |
| 340 | KXBTCD-26JUL0700-T62999.99 | yes | $+0.07 | — | — | — | missing_tick_day |
| 341 | KXETH15M-26JUL062330-30 | no | $+0.48 | — | — | — | unsupported_policy_scope |
| 342 | KXBTCD-26JUL0701-T63399.99 | no | $+0.08 | — | — | — | missing_tick_day |
| 344 | KXBTCD-26JUL0702-T63299.99 | no | $+0.06 | — | — | — | missing_tick_day |
| 346 | KXETHD-26JUL0702-T1769.99 | no | $-0.81 | — | — | — | missing_tick_day |
| 351 | KXBTCD-26JUL0703-T62799.99 | yes | $+0.10 | — | — | — | missing_tick_day |
| 352 | KXETH15M-26JUL070230-30 | yes | $+0.09 | — | — | — | unsupported_policy_scope |
| 354 | KXSOLD-26JUL0703-T80.9999 | yes | $+0.34 | — | — | — | missing_tick_day |
| 355 | KXETHD-26JUL0703-T1769.99 | yes | $+0.42 | — | — | — | missing_tick_day |
| 357 | KXHIGHDEN-26JUL07-T96 | no | $-0.63 | — | — | — | unsupported_policy_scope |
| 358 | KXBTCD-26JUL0704-T63099.99 | yes | $-0.34 | — | — | — | missing_tick_day |
| 359 | KXETHD-26JUL0704-T1769.99 | yes | $-1.09 | — | — | — | missing_tick_day |
| 360 | KXSOLD-26JUL0704-T81.9999 | no | $+0.22 | — | — | — | missing_tick_day |
| 366 | KXBTCD-26JUL0704-T63199.99 | no | $+0.12 | — | — | — | missing_tick_day |
| 368 | KXHIGHPHIL-26JUL07-B79.5 | no | $+0.36 | — | — | — | unsupported_policy_scope |
| 372 | KXBTCD-26JUL0705-T62799.99 | yes | $+0.11 | — | — | — | missing_tick_day |
| 373 | KXETH15M-26JUL070415-15 | no | $-0.88 | — | — | — | unsupported_policy_scope |
| 375 | KXSOLD-26JUL0705-T80.9999 | yes | $+0.22 | — | — | — | missing_tick_day |
| 376 | KXETH15M-26JUL070445-45 | no | $+0.11 | — | — | — | unsupported_policy_scope |
| 377 | KXSOLD-26JUL0706-T78.9999 | yes | $+0.07 | — | — | — | missing_tick_day |
| 379 | KXBTCD-26JUL0706-T63299.99 | no | $+0.09 | — | — | — | missing_tick_day |
| 382 | KXSOLD-26JUL0707-T83.9999 | no | $+0.11 | — | — | — | missing_tick_day |
| 383 | KXBTCD-26JUL0707-T63599.99 | no | $+0.12 | — | — | — | missing_tick_day |
| 384 | KXETHD-26JUL0707-T1789.99 | no | $+0.20 | — | — | — | missing_tick_day |
| 385 | KXETH15M-26JUL070630-30 | yes | $-0.71 | — | — | — | unsupported_policy_scope |
| 386 | KXETH15M-26JUL070645-45 | no | $+0.10 | — | — | — | unsupported_policy_scope |
| 389 | KXBTCD-26JUL0708-T63299.99 | no | $-0.43 | — | — | — | missing_tick_day |
| 391 | KXETH15M-26JUL070800-00 | yes | $-0.57 | — | — | — | unsupported_policy_scope |
| 392 | KXBTCD-26JUL0708-T63499.99 | no | $+0.07 | — | — | — | missing_tick_day |
| 393 | KXBTCD-26JUL0709-T63299.99 | yes | $+0.13 | — | — | — | missing_tick_day |
| 394 | KXETHD-26JUL0709-T1789.99 | no | $-1.01 | — | — | — | missing_tick_day |
| 395 | KXSOLD-26JUL0709-T81.9999 | no | $+0.28 | — | — | — | missing_tick_day |
| 397 | KXETH15M-26JUL070845-45 | no | $+0.48 | — | — | — | unsupported_policy_scope |
| 398 | KXETHD-26JUL0709-T1789.99 | no | $+0.01 | — | — | — | missing_tick_day |
| 400 | KXBTCD-26JUL0710-T63599.99 | no | $+0.11 | — | — | — | missing_tick_day |
| 401 | KXETHD-26JUL0710-T1789.99 | no | $+0.20 | — | — | — | missing_tick_day |
| 402 | KXSOLD-26JUL0710-T81.9999 | no | $+0.20 | — | — | — | missing_tick_day |
| 403 | KXETH15M-26JUL070915-15 | no | $+0.07 | — | — | — | unsupported_policy_scope |
| 404 | KXETH15M-26JUL071000-00 | yes | $-0.74 | — | — | — | unsupported_policy_scope |
| 406 | KXETHD-26JUL0711-T1789.99 | no | $+0.34 | — | — | — | missing_tick_day |
| 407 | KXBTCD-26JUL0711-T63599.99 | no | $+0.11 | — | — | — | missing_tick_day |
| 408 | KXSOLD-26JUL0711-T79.9999 | yes | $+0.20 | — | — | — | missing_tick_day |
| 413 | KXXRPD-26JUL0711-T1.1199 | no | $-2.30 | — | — | — | missing_tick_day |
| 415 | KXBTCD-26JUL0712-T62999.99 | yes | $+0.17 | — | — | — | missing_tick_day |
| 416 | KXETHD-26JUL0712-T1769.99 | yes | $+0.48 | — | — | — | missing_tick_day |
| 417 | KXSOLD-26JUL0712-T80.9999 | yes | $+0.54 | — | — | — | missing_tick_day |
| 418 | KXHIGHMIA-26JUL07-B92.5 | no | $-0.39 | — | — | — | unsupported_policy_scope |
| 420 | KXETH15M-26JUL071145-45 | yes | $+0.10 | — | — | — | unsupported_policy_scope |
| 421 | KXETH15M-26JUL071200-00 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 422 | KXBTCD-26JUL0713-T64299.99 | no | $+0.11 | — | — | — | missing_tick_day |
| 423 | KXETHD-26JUL0713-T1809.99 | no | $+0.25 | — | — | — | missing_tick_day |
| 426 | KXBTCD-26JUL0714-T63699.99 | yes | $+0.12 | — | — | — | missing_tick_day |
| 427 | KXETHD-26JUL0714-T1789.99 | yes | $+0.31 | — | — | — | missing_tick_day |
| 428 | KXXRPD-26JUL0714-T1.1199 | yes | $+0.17 | — | — | — | missing_tick_day |
| 429 | KXETH15M-26JUL071330-30 | no | $-2.52 | — | — | — | unsupported_policy_scope |
| 430 | KXSOLD-26JUL0714-T81.9999 | yes | $+0.37 | — | — | — | missing_tick_day |
| 431 | KXBTCD-26JUL0715-T63799.99 | yes | $-0.73 | — | — | — | missing_tick_day |
| 432 | KXSOLD-26JUL0715-T81.9999 | yes | $-1.01 | — | — | — | missing_tick_day |
| 434 | KXETHD-26JUL0715-T1809.99 | no | $+0.42 | — | — | — | missing_tick_day |
| 436 | KXBTCD-26JUL0716-T63999.99 | no | $+0.16 | — | — | — | missing_tick_day |
| 437 | KXETHD-26JUL0716-T1769.99 | yes | $+0.20 | — | — | — | missing_tick_day |
| 441 | KXBTCD-26JUL0717-T64249.99 | no | $+0.09 | — | — | — | missing_tick_day |
| 442 | KXSOLD-26JUL0717-T81.9999 | no | $+0.22 | — | — | — | missing_tick_day |
| 443 | KXSOLD-26JUL0716-T80.9999 | yes | $+0.28 | — | — | — | missing_tick_day |
| 446 | KXETHD-26JUL0717-T1789.99 | no | $+0.20 | — | — | — | missing_tick_day |
| 448 | KXETH15M-26JUL071715-15 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 449 | KXBTCD-26JUL0718-T63599.99 | yes | $-0.52 | — | — | — | missing_tick_day |
| 451 | KXBTCD-26JUL0718-T63299.99 | yes | $+0.17 | — | — | — | missing_tick_day |
| 452 | KXETHD-26JUL0718-T1769.99 | yes | $+0.37 | — | — | — | missing_tick_day |
| 453 | KXGPT-OPENB-26JUL10 | no | $-2.81 | — | — | — | unsupported_policy_scope |
| 454 | KXMEDNOMJUL-26AUG01-TJAC | no | $-1.40 | — | — | — | unsupported_policy_scope |
| 455 | KXSOLD-26JUL0718-T80.9999 | no | $+0.45 | — | — | — | missing_tick_day |
| 456 | KXXRPD-26JUL0718-T1.1199 | no | $+0.22 | — | — | — | missing_tick_day |
| 458 | KXETH15M-26JUL071800-00 | yes | $-0.65 | — | — | — | unsupported_policy_scope |
| 461 | KXBTCD-26JUL0719-T62999.99 | yes | $+0.14 | — | — | — | missing_tick_day |
| 466 | KXSOLD-26JUL0719-T80.9999 | no | $+0.28 | — | — | — | missing_tick_day |
| 468 | KXBTCD-26JUL0720-T63799.99 | no | $+0.07 | — | — | — | missing_tick_day |
| 470 | KXETHD-26JUL0720-T1769.99 | yes | $-1.39 | — | — | — | missing_tick_day |
| 476 | KXBTCD-26JUL0721-T63199.99 | yes | $+0.11 | — | — | — | missing_tick_day |
| 477 | KXXRPD-26JUL0721-T1.1199 | no | $+0.22 | — | — | — | missing_tick_day |
| 478 | KXSOLD-26JUL0721-T80.9999 | no | $+0.42 | — | — | — | missing_tick_day |
| 481 | KXETHD-26JUL0721-T1769.99 | yes | $+0.28 | — | — | — | missing_tick_day |
| 482 | KXETH15M-26JUL072100-00 | no | $+0.12 | — | — | — | unsupported_policy_scope |
| 484 | KXBTCD-26JUL0722-T63699.99 | no | $+0.09 | — | — | — | missing_tick_day |
| 485 | KXETHD-26JUL0722-T1769.99 | yes | $-1.52 | — | — | — | missing_tick_day |
| 486 | KXXRPD-26JUL0722-T1.1199 | no | $+0.17 | — | — | — | missing_tick_day |
| 487 | KXETH15M-26JUL072130-30 | no | $+0.48 | — | — | — | unsupported_policy_scope |
| 490 | KXBTCD-26JUL0723-T62599.99 | yes | $-0.35 | — | — | — | missing_tick_day |
| 491 | KXETH15M-26JUL072245-45 | no | $-0.65 | — | — | — | unsupported_policy_scope |
| 492 | KXSOLD-26JUL0723-T77.9999 | yes | $+0.48 | — | — | — | missing_tick_day |
| 493 | KXBTCD-26JUL0723-T62399.99 | yes | $+0.11 | — | — | — | missing_tick_day |
| 494 | KXETHD-26JUL0800-T1749.99 | yes | $-0.83 | — | — | — | missing_tick_day |
| 495 | KXBTCD-26JUL0800-T63299.99 | no | $+0.07 | — | — | — | missing_tick_day |
| 499 | KXSOLD-26JUL0801-T78.9999 | no | $+0.31 | — | — | — | missing_tick_day |
| 500 | KXBTCD-26JUL0801-T62999.99 | no | $+0.11 | — | — | — | missing_tick_day |
| 502 | KXETHD-26JUL0801-T1749.99 | yes | $+0.28 | — | — | — | missing_tick_day |
| 504 | KXBTCD-26JUL0802-T62499.99 | yes | $+0.09 | — | — | — | missing_tick_day |
| 505 | KXSOLD-26JUL0802-T78.9999 | no | $+0.20 | — | — | — | missing_tick_day |
| 506 | KXXRPD-26JUL0802-T1.0999 | no | $+0.17 | — | — | — | missing_tick_day |
| 507 | KXETHD-26JUL0802-T1749.99 | yes | $+0.45 | — | — | — | missing_tick_day |
| 509 | KXHIGHAUS-26JUL08-B97.5 | no | $+0.33 | — | — | — | unsupported_policy_scope |
| 510 | KXBTCD-26JUL0809-T62599.99 | no | $+0.10 | — | — | — | missing_tick_day |
| 511 | KXSOLD-26JUL0809-T76.9999 | yes | $-2.78 | — | — | — | missing_tick_day |
| 514 | KXETHD-26JUL0809-T1749.99 | no | $+0.06 | — | — | — | missing_tick_day |
| 515 | KXHIGHCHI-26JUL08-B90.5 | no | $+0.36 | — | — | — | unsupported_policy_scope |
| 516 | KXBTCD-26JUL0810-T62099.99 | no | $+0.20 | — | — | — | missing_tick_day |
| 517 | KXETHD-26JUL0810-T1749.99 | no | $+0.37 | — | — | — | missing_tick_day |
| 521 | KXSOLD-26JUL0810-T76.9999 | yes | $-1.13 | — | — | — | missing_tick_day |
| 522 | KXXRPD-26JUL0810-T1.0799 | yes | $-0.97 | — | — | — | missing_tick_day |
| 523 | KXETH15M-26JUL081000-00 | no | $+0.48 | — | — | — | unsupported_policy_scope |
| 524 | KXBTCD-26JUL0811-T62299.99 | no | $+0.16 | — | — | — | missing_tick_day |
| 525 | KXETHD-26JUL0811-T1749.99 | no | $+0.37 | — | — | — | missing_tick_day |
| 526 | KXETH15M-26JUL081030-30 | no | $-1.28 | — | — | — | unsupported_policy_scope |
| 528 | KXBTCD-26JUL0812-T62099.99 | no | $+0.12 | — | — | — | missing_tick_day |
| 529 | KXETHD-26JUL0812-T1709.99 | yes | $+0.25 | — | — | — | missing_tick_day |
| 530 | KXHIGHMIA-26JUL08-B91.5 | yes | $+1.68 | — | — | — | unsupported_policy_scope |
| 532 | KXXRPD-26JUL0812-T1.0799 | no | $+0.25 | — | — | — | missing_tick_day |
| 534 | KXETH15M-26JUL081200-00 | yes | $+0.11 | — | — | — | unsupported_policy_scope |
| 542 | KXBTCD-26JUL0813-T62099.99 | no | $+0.08 | — | — | — | missing_tick_day |
| 543 | KXETH15M-26JUL081215-15 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 547 | KXBTCD-26JUL0814-T62299.99 | no | $-0.35 | — | — | — | missing_tick_day |
| 548 | KXSOLD-26JUL0814-T76.9999 | yes | $-0.88 | — | — | — | missing_tick_day |
| 549 | KXETHD-26JUL0814-T1729.99 | yes | $+0.20 | — | — | — | missing_tick_day |
| 559 | KXBTCD-26JUL0817-T62499.99 | no | $+0.12 | — | — | — | missing_tick_day |
| 560 | KXETHD-26JUL0817-T1749.99 | no | $+0.34 | — | — | — | missing_tick_day |
| 562 | KXXRPD-26JUL0817-T1.0799 | yes | $+0.20 | — | — | — | missing_tick_day |
| 563 | KXBTCD-26JUL0816-T62299.99 | no | $+0.10 | — | — | — | missing_tick_day |
| 564 | KXSOLD-26JUL0816-T76.9999 | yes | $+0.25 | — | — | — | missing_tick_day |
| 565 | KXETH15M-26JUL081600-00 | no | $-2.52 | — | — | — | unsupported_policy_scope |
| 567 | KXSOLD-26JUL0817-T76.9999 | yes | $-1.07 | — | — | — | missing_tick_day |
| 568 | KXETH15M-26JUL081630-30 | no | $-2.52 | — | — | — | unsupported_policy_scope |
| 570 | KXBTCD-26JUL0818-T62199.99 | no | $+0.27 | — | — | — | missing_tick_day |
| 571 | KXFEDDECISION-26JUL-H0 | no | $+0.28 | — | — | — | unsupported_policy_scope |
| 572 | KXRT-ODY-90 | no | $+0.09 | — | — | — | unsupported_policy_scope |
| 573 | KXSOLD-26JUL0818-T76.9999 | yes | $+0.39 | — | — | — | missing_tick_day |
| 574 | KXETHD-26JUL0818-T1729.99 | yes | $+0.17 | — | — | — | missing_tick_day |
| 575 | KXETH15M-26JUL081800-00 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 576 | KXBTCD-26JUL0819-T61999.99 | yes | $+0.10 | — | — | — | missing_tick_day |
| 577 | KXETHD-26JUL0819-T1729.99 | yes | $+0.20 | — | — | — | missing_tick_day |
| 580 | KXSOLD-26JUL0819-T76.9999 | yes | $+0.28 | — | — | — | missing_tick_day |
| 581 | KXSOLD-26JUL0820-T76.9999 | yes | $+0.17 | — | — | — | missing_tick_day |
| 585 | KXETH15M-26JUL081930-30 | no | $+0.48 | — | — | — | unsupported_policy_scope |
| 587 | KXBTCD-26JUL0821-T62399.99 | no | $+0.07 | — | — | — | missing_tick_day |
| 589 | KXETHD-26JUL0821-T1729.99 | yes | $+0.20 | — | — | — | missing_tick_day |
| 590 | KXSOLD-26JUL0821-T77.9999 | no | $+0.31 | — | — | — | missing_tick_day |
| 591 | KXETH15M-26JUL082030-30 | no | $+0.48 | — | — | — | unsupported_policy_scope |
| 592 | KXBTCD-26JUL0822-T61899.99 | yes | $-0.88 | — | — | — | missing_tick_day |
| 593 | KXETHD-26JUL0822-T1729.99 | yes | $-2.66 | — | — | — | missing_tick_day |
| 595 | KXSOLD-26JUL0822-T78.9999 | no | $+0.22 | — | — | — | missing_tick_day |
| 600 | KXSOLD-26JUL0823-T76.9999 | yes | $-1.36 | — | — | — | missing_tick_day |
| 601 | KXBTCD-26JUL0823-T62199.99 | no | $+0.12 | — | — | — | missing_tick_day |
| 603 | KXETH15M-26JUL082300-00 | no | $-0.39 | — | — | — | unsupported_policy_scope |
| 604 | KXBTCD-26JUL0900-T61999.99 | no | $+0.10 | — | — | — | missing_tick_day |
| 605 | KXETH15M-26JUL082315-15 | no | $+0.14 | — | — | — | unsupported_policy_scope |
| 606 | KXETH15M-26JUL082345-45 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 607 | KXSOLD-26JUL0900-T76.9999 | yes | $-1.18 | — | — | — | missing_tick_day |
| 608 | KXBTCD-26JUL0901-T62199.99 | no | $-0.50 | — | — | — | missing_tick_day |
| 609 | KXETHD-26JUL0901-T1739.99 | no | $-1.35 | — | — | — | missing_tick_day |
| 612 | KXSOLD-26JUL0901-T77.9999 | no | $+0.25 | — | — | — | missing_tick_day |
| 614 | KXETH15M-26JUL090145-45 | yes | $+0.10 | — | — | — | unsupported_policy_scope |
| 617 | KXHIGHPHIL-26JUL09-B85.5 | no | $+0.36 | — | — | — | unsupported_policy_scope |
| 623 | KXHIGHMIA-26JUL09-B94.5 | no | $+0.30 | — | — | — | unsupported_policy_scope |
| 627 | KXETH15M-26JUL090700-00 | no | $+0.48 | — | — | — | unsupported_policy_scope |
| 630 | KXETH15M-26JUL090800-00 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 631 | KXETH15M-26JUL090815-15 | no | $+0.48 | — | — | — | unsupported_policy_scope |
| 634 | KXBTCD-26JUL0909-T62899.99 | no | $+0.09 | — | — | — | missing_tick_day |
| 640 | KXETH15M-26JUL090930-30 | no | $+0.48 | — | — | — | unsupported_policy_scope |
| 646 | KXBTCD-26JUL0910-T62999.99 | no | $-0.67 | — | — | — | missing_tick_day |
| 648 | KXETH15M-26JUL091000-00 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 655 | KXETH15M-26JUL091030-30 | no | $+0.08 | — | — | — | unsupported_policy_scope |
| 656 | KXETH15M-26JUL091100-00 | no | $-2.52 | — | — | — | unsupported_policy_scope |
| 657 | KXHIGHNY-26JUL09-B83.5 | no | $+0.60 | — | — | — | unsupported_policy_scope |
| 659 | KXFEDDECISION-26JUL-H25 | yes | $+0.36 | — | — | — | unsupported_policy_scope |
| 663 | KXETH15M-26JUL091300-00 | no | $-0.92 | — | — | — | unsupported_policy_scope |
| 664 | KXETH15M-26JUL091315-15 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 675 | KXBTCD-26JUL0917-T63249.99 | no | $-0.25 | — | — | — | missing_tick_day |
| 676 | KXETH15M-26JUL091645-45 | yes | $+0.48 | — | — | — | unsupported_policy_scope |
| 678 | KXETH15M-26JUL091715-15 | yes | $-0.68 | — | — | — | unsupported_policy_scope |
| 683 | KXBTCD-26JUL0918-T63099.99 | yes | $+0.07 | — | — | — | missing_tick_day |
| 684 | KXETH15M-26JUL091930-30 | no | $-2.52 | — | — | — | unsupported_policy_scope |
| 686 | KXHIGHCHI-26JUL10-B81.5 | no | $-0.66 | — | — | — | unsupported_policy_scope |
| 689 | KXBTCD-26JUL1004-T63999.99 | no | $+0.08 | — | — | — | missing_tick_day |
| 691 | KXHIGHNY-26JUL10-B87.5 | no | $+0.32 | — | — | — | unsupported_policy_scope |
| 695 | KXETHD-26JUL1005-T1769.99 | yes | $+0.12 | — | — | — | missing_tick_day |
| 696 | KXBTCD-26JUL1005-T64099.99 | no | $-0.61 | — | — | — | missing_tick_day |
| 698 | KXBTCD-26JUL1006-T64499.99 | no | $+0.11 | — | — | — | missing_tick_day |
| 700 | KXBTCD-26JUL1007-T64399.99 | no | $-0.37 | — | — | — | missing_tick_day |
| 703 | KXBTCD-26JUL1008-T64399.99 | no | $-0.40 | — | — | — | missing_tick_day |
| 707 | KXXRPD-26JUL1010-T1.0999 | yes | $+0.11 | — | — | — | missing_tick_day |
| 708 | KXETHD-26JUL1010-T1789.99 | yes | $+0.29 | — | — | — | missing_tick_day |
| 709 | KXBTCD-26JUL1010-T63999.99 | yes | $+0.13 | — | — | — | missing_tick_day |
| 710 | KXSOLD-26JUL1010-T78.9999 | no | $-0.15 | — | — | — | missing_tick_day |
| 713 | KXHIGHPHIL-26JUL10-B86.5 | yes | $+1.66 | — | — | — | unsupported_policy_scope |
| 728 | KXBTCD-26JUL1017-T63999.99 | no | $+0.07 | — | — | — | missing_tick_day |
| 734 | KXBTCD-26JUL1019-T63999.99 | no | $-0.10 | — | — | — | missing_tick_day |
| 738 | KXBTCD-26JUL1019-T64099.99 | no | $-0.35 | — | — | — | missing_tick_day |
| 739 | KXBTCD-26JUL1019-T64099.99 | no | $-0.06 | — | — | — | missing_tick_day |
| 740 | KXBTCD-26JUL1021-T64199.99 | no | $+0.17 | $+0.01 | $-0.16 | early_capture / early_far | REPLAYED |
| 751 | KXBTCD-26JUL1100-T64199.99 | no | $+0.18 | $-0.17 | $-0.35 | dual_stop / early_near | REPLAYED |
| 752 | KXBTCD-26JUL1101-T64199.99 | no | $+0.16 | $+0.03 | $-0.13 | early_capture / early_far | REPLAYED |
| 759 | KXBTCD-26JUL1103-T63999.99 | yes | $+0.07 | $+0.03 | $-0.04 | early_capture / early_far | REPLAYED |
| 760 | KXHIGHAUS-26JUL11-B91.5 | no | $+0.37 | — | — | — | unsupported_policy_scope |
| 761 | KXHIGHLAX-26JUL11-B75.5 | no | $+0.36 | — | — | — | unsupported_policy_scope |
| 762 | KXHIGHNY-26JUL11-T81 | no | $+2.65 | — | — | — | unsupported_policy_scope |
| 763 | KXHIGHDEN-26JUL12-B96.5 | no | $+0.35 | — | — | — | unsupported_policy_scope |
| 764 | KXHIGHNY-26JUL12-B84.5 | no | $-0.68 | — | — | — | unsupported_policy_scope |
| 765 | KXHIGHPHIL-26JUL12-B86.5 | no | $+0.53 | — | — | — | unsupported_policy_scope |
| 769 | KXPCECORE-26JUN-T0.2 | yes | $-0.57 | — | — | — | unsupported_policy_scope |

## 假设与局限

- tick schema contains Kalshi order-book quotes only; it has no Coinbase/CF index spot, strike metadata table, or 24h realized-volatility series.
- The script infers a spot proxy as the ladder strike where contemporaneous YES probability crosses 0.5. This quote-implied median is endogenous to Kalshi and cannot reproduce the registered unmanipulable spot confirmation.
- Because 24h composite RV is unavailable, non-macro observations use production's blind-data fallback `elevated` (0.075%); registered macro windows use `storm` (0.10%). Calm/storm RV thresholds remain frozen but cannot be observed.
- 15-minute crypto contracts are skipped: their reference is the prior window's published settlement, which is absent from tick DBs. Weather and event contracts are outside this hourly crypto τ policy.
- Naive ledger timestamps are interpreted using US Mountain time; ticker close codes use US Eastern wall time. Standard US DST rules convert both to UTC.
- Execution is conservative: signal on one snapshot, fill no earlier than the next snapshot, require full displayed top-of-book depth, charge the general taker fee, and subtract an extra 2c on dual-stop fills. Hidden depth, queue priority, partial fills, and favorable improvement are ignored.
- Maximum drawdown uses chronological realized P&L on the paired subset, not unavailable intratrade portfolio mark-to-market. Total EV difference is the paired realized-P&L difference.
- A position is skipped for a missing day, empty ticker path, a boundary/internal gap above five times empirical median cadence (at least 5s), an unavailable proxy at a policy decision, or an unknown terminal result when policy holds.

## 只读与 schema 审计

- ledger URI：`mode=ro`；trades 列：id, ts, mode, ticker, title, side, price, contracts, cost_usd, fee_usd, q_claude, q_codex, q_consensus, market_prob, edge_net, rationale, status, result, pnl_usd, settled_ts, order_id, exit_type, target_price, stop_price, review_after_ts, exit_price, booked_ts。
- tick 数据库均以 `mode=ro` 打开；仅在沙箱无法取得历史文件共享锁时追加 `immutable=1`，并在 JSON 的 `open_modes` 留痕。
- 配置冻结值核对：全部一致。
