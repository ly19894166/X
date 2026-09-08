# Phase 6：事件→产业→公司→A股证券传导图

输入规范：总体技术规范 V0.1 §7.2、Issue #11、Phase4 A1 compatibility contract、
Phase5 已接受门槛及本轮用户 Phase6 指令。唯一基线：
`build/x-event-engine-phase5 @ 36ebcc31e6d0f930833ec27905523cfb0f745b5f`。
以该分支为 base 建立 stacked Draft PR；不合并 PR #21 或其他 PR。

## 正式对象与职责

| 对象 | 职责 |
| --- | --- |
| EdgeVersion | 固定 from/to、类型、世界、目标方向、机制、推断类别、边证据、Origin 和完整派生信封 |
| TransmissionPath | 固定有序节点/边、事件/产业候选/暴露/公司/证券、原暴露等级、深度、方向、研究状态 |
| MappingAssessment | 每公司保留正/负/叙事全部路径与净状态，不计算净收益分数 |
| MappingHistory | 完整 BuildRequest、输入截止点、路径/assessment 引用、前次历史和 HOLD |
| BuildRequest | 固定 Event、IndustryResolution 列表、CompanyExposure 列表、ResearchUniverseSnapshot 及 as_of |

所有正式对象沿用 DerivedEnvelope，保留 object_id/version、recorded_at、computed_at、
available_at、input_version_refs、policy_version、provenance_zh。策略为 `X_TRANSMISSION_V0.1`。
输入无用户持仓、成本、交易权限或价格。

## 路径规则

经济链：Event → 一条或多条显式 Impact 前提 → IndustrySegment → CompanyExposure → Company → Security。
只使用 Phase4 已发布的 IndustryResolution/IndustryImpactCandidate，不重新解析关键词。
候选的 industry_ref 必须与 exposure.industry_ref **固定版本相等**；
path_role 与 business_role 必须相等。未知或不同角色留 HOLD，不能把生产者机制套给投入使用者。
公司用已核验稳定 ID 对齐当前 PIT 身份，证券必须来自已发布全A股研究快照的 INCLUDED 决策。
不得用公司名、证券简称或产业别名寻找没有暴露依据的公司。

Phase4 的类型、UP/DOWN、target、geography、FX pair、confidence、机制、ontology/version、
observation_kind、uncertainty、premise_refs 均通过固定 Impact/Candidate 引用保留；不复制可漂移的新字段。
图层不把 SUPPLY/DOWN 直接改写成 PRICE/UP。fixture 显式保存“宣布减产观察”及“价格上涨假设”两个对象。
本 Phase 所有经济结果仍为 `PLAUSIBLE`（反证未解除可为 `CONTRADICTED`），
不会因规则或公司暴露 VERIFIED 而升级为已经验证的经济效果。

经济深度 = 当前路径显式 Impact 节点数 + Impact→Industry 一层；
Industry→Exposure→Company→Security 是结构关系，不增加经济深度。
1/2/3层分别对应 L1/L2/L3，层数等级不是事实可信度或盈利概率。
超过3层保留 L3路径并标 DEGRADED / ECONOMIC_DEPTH_REVIEW_REQUIRED；不删除原前提。
只遍历已存在的显式前提，不扩展新产业链；128层或单节点1024条分支的资源上限触发
HOLD_GRAPH_RESOURCE_BOUND 并回滚该次构建，输入保持留存。不以无限递归寻找公司。

边逐对生成，节点自环/重复身份、边数不连续、端点错误、悬空固定输入均拒绝。
边 evidence_refs 按此边所用候选、Impact前提、暴露或证券归属选择；
全输入审计闭包放 input_version_refs，不宣称所有材料都是每条边的支持。
完整路径保存业务披露引用，Phase5 的 immutable raw/source span 等原有核验不变。

## 叙事与冻结字段的正规化对应

叙事链：Event → NarrativeTheme → CompanyExposure(NARRATIVE_ASSOCIATION) → Company → Security。
Phase5 的该类 CompanyExposure 是冻结 §7.2 `MarketAssociation` 的唯一正规化存储：
association_id = exposure_id，theme_ref = narrative_theme_ref，company_ref/evidence_refs/available_at 原样引用。
不另建第二份可漂移的关联记录；不会把 ThemeIndustryRelation 当成业务暴露。

叙事路径只有 N1_NARRATIVE / NARRATIVE_ONLY，方向 UNKNOWN，不计入经济净状态。
市场关联需具名核验及既有 DisclosureImport 的原文片段同时定位主题规范名称和公司名称；
片段存在性复用 Phase5 导入校验。缺定位记录 NARRATIVE_ASSOCIATION_PROOF_REQUIRED。
这是对明确关联的保守入口，不是自动语义理解，也不能证明经济受益。
没有公司关联材料的主题可以继续留在 Phase4，但不编造对应公司/证券路径。

## CompanyExposure 与研究证券范围

VERIFIED_DIRECT 仍仅允许 MANUAL_VERIFIED；EXACT_ALIAS_REVIEWED / VERIFIED_RULE 不开放。
SUPPORTED_DIRECT、INFERRED、UNKNOWN、HOLD 原等级逐路径保存；后两者研究状态 HOLD。
历史报告期暴露可以保留路径，但已结束或尚未开始的业务区间标
HISTORICAL_EXPOSURE_CONTINUITY_UNVERIFIED；不将去年业务默认为目前仍持续。
图层不会用墙钟否定历史披露引用的退休产业版本，也不会自动替换成新产业版本。

快照必须先发布且 available_at<=图输入as_of。快照本身的 as_of 与图输入截止分别保存。
快照发布后到图计算截止间发生更名、退市、公司/证券归属修订或身份冲突时，
对应证券留 SNAPSHOT_REFRESH_REQUIRED/SECURITY_IDENTITY_COLLISION，需重新发布研究快照。
再次核对 listing_date/delisting_date 及现实有效区间，不沿用已经失效的 INCLUDED 决策。
ST、停牌、创业/科创/北交等沿用 Phase5 研究定义；没有执行账户筛选。
未出现在该快照中的后来新增证券不会自动补入，不声称真实全A股覆盖。

## 净状态、反路径与反查

按公司保留所有正负路径，正负并存为 MIXED；UNKNOWN 不等于 NEUTRAL。
若任一经济路径 HOLD，净状态 HOLD，但原始方向与路径分组仍完整。
没有经济路径但有叙事路径时，经济净状态 UNKNOWN。
反路径按较短经济深度、固定ID排序选一个展示定位，字段明确
`DEPTH_THEN_FIXED_ID_NOT_ALPHA`；没有反路径则 null，不伪造“最强反证”或评分。
这只是可审计展示顺序，不声称统计强度、实际经济力量或 Phase7 Red Team 已完成。

`reverse(company_or_security_id, as_of)` 只读最新 MappingHistory 的既有路径，
活跃过滤复用 Phase3 EventStateSnapshot：归档/INVALIDATED 不列入活跃结果。
后来事件/暴露/证券/同源修订尚未重算时，返回 recompute_reasons，旧路径不冒充新计算。
`alternatives(company_id, industry_ref, as_of)` 只返回已保存的同固定产业其他公司路径。
它不搜索新事件理由，也不排序股票；调用方可查看路径的原计算时间和 HOLD。

Origin 复用 Phase2 不可变 OriginClusterVersion 和显式 CONFIRMED_SAME_ORIGIN 关系。
路径保存固定簇版本及规范分组ID；不输出来源次数、传导权重或重复加分。
70次转载依然只是同一根消息的正/负机制组，保留各事件原始路径作为审计材料。
后来合源需显式追加 MappingHistory，新分组只对新版本生效；不改旧 as_of。
调度仍使用既有 Phase3 重算任务，本阶段不新增后台自动研究。

## PIT、版本与事务

构建先限制所有原始节点及其传递输入 available_at<=as_of，且模式为 LIVE_FORWARD。
已知新版 Event/Exposure 不允许用旧版本规避重述；旧 as_of 仍可读取旧知识。
图的边/路径/assessment/history 是计算后新产物：available_at 不得伪装成输入截止点。
10:15 不得读10:30解析/11:00暴露；它们发布后才能生成完整图。
用 ledger.history/replay 的实际可用时间读取结果，不用输入as_of当成已发布时间。

所有输出在同一 Phase2 事务中发布，复用 WAL、不可变 records、提交后回执及 publication fence。
没有新SQL表、迁移或依赖；Ledger只注册4种新模型。故障回滚不留下半张图。
同 history_id/version 与相同请求幂等；不同请求冲突，修订必须追加下一历史版本。
图内成员版本使用所属 history 修订号；新出现的路径可从该修订号开始，
不是独立连续计数器。历史集合由 MappingHistory 固定引用，不使用动态latest作为持久化依据。
旧代码不能读取新增kind；不自动向旧数据库补写新图或改变任何旧payload。

## 离线使用与未验证状态

```text
python -m xevent.graph.fixture --db phase6-demo.sqlite
x-event schema --model TransmissionPath
python -m pytest -q tests/test_phase6_graph.py tests/test_phase6_history.py
python -m pytest -q
python -m pytest -q -m pit
```

fixture 是虚构综合公司的铜生产/耗铜业务，只演示机制与 PIT。
输出明确：**这是工程演示，不代表真实Alpha或投资建议。**
实际测试和CI结果见 PHASE6_VALIDATION.md。

保留 HOLD_HISTORICAL_UNIVERSE_COVERAGE、HOLD_REAL_COMPANY_EXPOSURE_COVERAGE、
HOLD_PRE_1992_CALENDAR、HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION。
真实机制、未来利润影响、叙事语义真实性、真实全市场覆盖及Live均未验收。
无新依赖；既有锁/许可证不变。无网络、LLM、价格、排名、推荐或交易。
不修改 Market Engine、src/xalpha、PR #2或Issue #1，不进入Phase7。

工程能力完成 ≠ 真实全A股数据覆盖完成 ≠ 真实Alpha成立。
Issue #11保持OPEN，PR保持Draft，等待人工复审。
