# 事件盘首轮研究笔记

研究截止：2026-07-10 11:11:46 UTC

## 方法与盲法说明

每个事件用了两套独立框架：`inside_view` 根据当前事件的执行机制、时间表和领先状态更新；`outside_view` 从同类事件基率、竞争集大小或历史分布出发，再有限度吸收当前事实。`opus_inside` 和 `opus_outside` 是 Codex 草稿，已在各自 `key_drivers[0]` 标注 `[CODEX-DRAFT 待Fable仲裁]`。

没有主动搜索、打开或引用 Kalshi 盘口，研究查询也避开了市场、赔率和价格词。但模板本身含有 `arbiter_market_snapshot`；我在第一次完整核对 JSON 结构时看到了该区域。后来一次关于 Spotify 月听众的中性 Exa 查询还意外返回了预测市场搜索结果。两次内容都没有进入下述论证或估计公式，但严格意义上的盲法已受污染。按任务要求，JSON 内所有 `market_price_seen` 仍保持 `false`。Fable 应决定废弃本批，或从只含 `blind` 字段的净化模板重跑。

## 1. Ariana Grande 七月 Spotify 全球日榜第 1 至少 12 天

截至 7 月 8 日，Kworb 的单曲日度历史显示 `hate that i made you love me` 在七月的名次依次为 1、1、4、4、4、2、2、1，因此已取得 3 个榜首日。7 月 8 日播放量约 432 万，第二名约 422 万，差距只有约 10 万。她还需在 7 月 9 日至 31 日的 23 个榜日中拿到 9 天第 1。

时事框架认为当前仍是可反复夺冠的近身竞争，3/8 的实现率与剩余所需的 9/23 接近。基率框架更保守：歌曲已发行约六周，剩余期间跨过三个主要发行周五，榜首竞争集会刷新。7 月 31 日的新专辑 `petal` 来得太晚，最多直接帮助很少的七月榜日。

估计：opus_inside 0.42，opus_outside 0.34，codex_inside 0.44，codex_outside 0.33。区间较宽，因为阈值正落在按当前频率外推的中部，而且榜首日高度相关。

来源：

- [Kworb 单曲日度 Spotify 历史](https://kworb.net/spotify/track/20jbSiX29FDX4oQxBXyUEi.html)，数据截至 2026-07-08。
- [Universal Music Canada：`petal` 将于 7 月 31 日发行](https://www.universalmusic.ca/press-releases/ariana-grande-announces-eighth-studio-album-petal-to-be-released-july-31/)，2026-04-28。
- [Billboard：首支单曲于 5 月 29 日上线](https://www.billboard.com/music/pop/ariana-grande-hate-that-i-made-you-love-me-stream-it-now-1236259537/)，2026-05-29。
- [Official Charts：7 月 10 日新发行清单](https://www.officialcharts.com/chart-news/new-music-friday-playlist-songs-singles-albums-dvds-9th-july-2026/)，2026-07-09。

最有价值的新信息是未来一周的实际榜首日。若再拿 4 天以上，概率应升到约 0.65；若一日未得，应降到 0.20 以下。

## 2. Dan Kleban 成为 Maine 民主党参议员提名人

Graham Platner宣布退出后，Maine 民主党计划在 7 月 27 日法定截止日前开约 600 人的提名大会，其中约 500 名代表由县级组织选出，另有 100 多名州委员会成员。至少 8 人已宣布争取提名。Kleban 是 Maine Beer Company 联合创始人，2025 年曾参加这场参议员竞选，但在 Janet Mills 入局后退出。他有商业局外人叙事，却没有近期州级得票或已公开的大型代表块。

时事框架把党内组织和快速背书看得最重：Troy Jackson 宣布后数小时已有 50 多项背书，Nirav Shah 和 Shenna Bellows 也刚完成全州初选。基率框架从多人均分起步，再因 Kleban 缺少近期选举验证和党内职位而折价。小概率上行路径是大会多轮死锁后，代表转向一个声誉包袱较少的妥协人选。

估计：opus_inside 0.055，opus_outside 0.07，codex_inside 0.05，codex_outside 0.065。

来源：

- [Maine 民主党领导层要求 Platner 退出](https://mainedems.org/statement-from-maine-democratic-party-leadership-on-allegations-against-graham-platner/)，2026-07-06。
- [Maine Public：已宣布的替补候选人](https://www.mainepublic.org/politics/2026-07-09/now-that-graham-platner-is-out-who-is-running-to-replace-him)，2026-07-09。
- [Bangor Daily News：约 600 名代表与竞选组织情况](https://www.bangordailynews.com/2026/07/09/politics/elections/democrats-running-replace-graham-platner/)，2026-07-09。
- [Axios：主要候选人的履历和相对优势](https://www.axios.com/2026/07/09/democrats-maine-senate-race-replace-platner)，2026-07-09。

公开代表计数会直接替代当前的低信息先验。Kleban若进入前三或获得主要工会、全州民选官员支持，才应显著上调。

## 3. Nirav Shah 成为 Maine 民主党参议员提名人

Shah 刚参加民主党州长初选，并进入最终两强。他拥有全州知名度、名单和可重启的竞选组织。参议员替补竞选启动时，他强调与 Platner 在 Medicare for All、贫困和对外政策上的接近，同时拒绝寻求 Platner 本人的背书。这种切割试图保留进步派政策延续，又避免继承丑闻。

时事框架把 Shah 视为三名第一梯队候选人之一。他可能在多轮大会中成为较广的第二选择。基率框架从至少 8 人的竞争集出发，因其近期全州表现上调，但提醒大会代表不是初选选民的随机样本。Jackson 的工会和 Platner 基层关系、Bellows 的现任州务卿网络都可能更适合代表制程序。

估计：opus_inside 0.23，opus_outside 0.19，codex_inside 0.24，codex_outside 0.20。

来源：

- [Bangor Daily News：Shah 宣布争取替补提名](https://www.bangordailynews.com/2026/07/09/politics/elections/maine-election-senate-nirav-shah-campaign-graham-platner-replacement/)，2026-07-09。
- [Bangor Daily News：候选人争取 Platner 基层及代表](https://www.bangordailynews.com/2026/07/09/politics/elections/democrats-graham-platners-base/)，2026-07-09。
- [Maine Secretary of State：州长初选 ranked-choice 计票完成](https://www.maine.gov/sos/news/maine-secretary-states-office-announces-ranked-choice-tabulations)，2026-06-19。
- [Axios：主要替补候选人比较](https://www.axios.com/2026/07/09/democrats-maine-senate-race-replace-platner)，2026-07-09。

不确定性的核心不是普通选民偏好，而是尚未完全公布的代表选择规则和首轮承诺。县级代表名单出来后，当前 0.08 至 0.40 的宽区间可以大幅收窄。

## 4. 《The Odyssey》在指定时点的 Tomatometer 严格高于 85

截至研究截止时，Rotten Tomatoes 页面仍显示 0 篇评论。7 月 6 日伦敦首映后，社交反应禁令已解除；Variety、Hollywood Reporter、Time Out、Guardian、LA Times、IndieWire 等评论岗位人员的反应近乎一致正面。可见的保留意见主要是叙事“笨重”或改编取舍，而非整体负评。完整评论预计 7 月 15 日解禁，电影 7 月 17 日广泛上映，结算在 7 月 20 日上午。

时事框架把这些发言视为未来合格 Tomatometer 评论人的提前样本，给出约 0.90。基率框架统计 Forbes 列出的 12 部 Nolan 长片：7 部严格高于 85，未经新片信息的基率约 0.58。首波反应作强更新后得到约 0.75，但仍折扣首映礼礼貌、宣传筛选和社交反应偏乐观。严格“大于 85”也意味着 85 本身失败。

估计：opus_inside 0.92，opus_outside 0.75，codex_inside 0.90，codex_outside 0.76。

来源：

- [Rotten Tomatoes 影片页](https://www.rottentomatoes.com/m/the_odyssey_2026)，截至 2026-07-10 为 0 篇评论。
- [Variety：首波反应汇总](https://variety.com/2026/film/news/the-odyssey-first-reactions-christopher-nolan-1236802321/)，2026-07-06。
- [Hollywood Reporter：专业媒体首波反应](https://www.hollywoodreporter.com/movies/movie-news/the-odyssey-first-reactions-reviews-1236638991/)，2026-07-06。
- [Forbes：首波评价与 Nolan 历史 Tomatometer](https://www.forbes.com/sites/paultassi/2026/07/07/the-odyssey-early-critic-reviews-render-a-unanimous-verdict/)，2026-07-07。
- [Metro：完整评论于 7 月 15 日解禁](https://metro.co.uk/2026/07/07/odyssey-hailed-cinematic-triumph-first-reactions-christopher-nolans-epic-29075208/)，2026-07-07。

7 月 15 日的前 30 至 50 篇正式评论是决定性更新。若其中 Rotten 比例超过 20%，当前高概率应明显下调。

## 5. Bruno Mars 在 7 月 31 日成为 Spotify 月听众最多的艺人

Spotify公开艺人页在研究时点显示 Bruno 约 1.336 亿月听众、Justin Bieber 约 1.253 亿。不同抓取时点的第三方页面给出的领先约 600 万至 800 万。Chartmasters 的 7 月 8 日快照还显示，Bruno 过去 30 天约减少 470 万，Justin 约减少 770 万；两人都从高位回落，但 Justin 更快。第三名附近约 1.14 亿，离 Bruno 近两千万，因此主要失败路径几乎都来自 Justin。

时事框架认为 Bruno 的 `The Romantic` 专辑推广和欧洲体育场巡演能支撑覆盖，而 Justin 的主要冲击来自 4 月 Coachella，正在退出 28 天滚动窗口。基率框架更重视尾部：Billboard Canada 记录 Justin 在约 24 天内从约 9900 万升到超过 1.4 亿，证明大型现场或新发行可以轻易跨越当前差距。

估计：opus_inside 0.91，opus_outside 0.83，codex_inside 0.92，codex_outside 0.84。

来源：

- [Bruno Mars Spotify 公开页](https://open.spotify.com/artist/0du5cEVh5yTK9QJze8zA0C)，抓取于 2026-07-10。
- [Justin Bieber Spotify 公开页](https://open.spotify.com/artist/1uNFoZAHBGtllmzznpCI3s)，抓取于 2026-07-10。
- [Chartmasters 月听众日榜](https://chartmasters.org/most-monthly-listeners-on-spotify/)，数据截至 2026-07-08。
- [Billboard Canada：Justin 的 Coachella 月听众跃升](https://ca.billboard.com/business/streaming/justin-bieber-spotify-monthly-listeners)，2026-05-04。

需要监控两件事：差距是否每周收窄超过约 200 万，以及 Justin 是否确认大型发行或合作。没有这两类信号，常态漂移不足以在三周内反超。

## 6. Donald Trump 出席 2026 FIFA 世界杯决赛

FIFA主席 Gianni Infantino 已在电视采访中明确表示会与 Trump 一起观看 7 月 19 日决赛，并共同把奖杯交给冠军。Trump 在 2025 年已到同一座 MetLife 体育场参加世俱杯决赛，与 Infantino 完成几乎相同的颁杯动作。决赛地点靠近 Trump 经常前往的纽约和 Bedminster，规则又允许短暂或部分出席。

时事框架把具体角色、同场馆先例和双方密切关系合并，给出约 0.97。基率框架把第三方主办机构的公开安排与白宫正式日程区分开，为最后一刻的安全、健康、外交和总统行程变化保留约一成失败率。研究截止时还没有 7 月 19 日的白宫正式周末指引。

估计：opus_inside 0.97，opus_outside 0.91，codex_inside 0.97，codex_outside 0.90。

来源：

- [BBC：Infantino确认Trump将出席并颁杯](https://www.bbc.com/sport/football/articles/cze9wp8r6lno)，2026-06-23。
- [FIFA：决赛于7月19日在New York New Jersey Stadium举行](https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/fifa-world-cup-26-match-schedule-revealed)，截至 2026-07-10。
- [CNBC：双方关系、赠票和2025年同场馆先例](https://www.cnbc.com/2026/07/01/trump-fifa-infantino-world-cup-financial-disclosure.html)，2026-07-01。
- [Reuters转述：具体共同颁杯安排](https://www.aljazeera.com/sports/2026/6/23/donald-trump-to-attend-world-cup-final-present-trophy-infantino)，2026-06-23。
- [AP：Trump与Infantino在本届赛事中的持续互动](https://www.clickorlando.com/news/politics/2026/07/06/red-card-furor-puts-trump-and-infantinos-relationship-under-the-spotlight-again/)，2026-07-06。

最后 48 小时的白宫周末指引、当地安保通告或总统旅行禁飞区最能收窄剩余不确定性。

## 总结

这批研究能较清楚地区分“公开安排已经形成”的事件与“仍需多人竞争或日度累积”的事件。Trump出席、Bruno月听众榜首和《The Odyssey》影评分数有较强事实信号；Maine两项的主要信息尚未出现；Ariana门槛正处于当前外推的中间，诚实区间必须保持宽。

因为严格盲法已被模板内嵌字段和一次搜索结果意外污染，本轮不做任何 `edge` 判断，也不把与盘口的差异写入结论。
