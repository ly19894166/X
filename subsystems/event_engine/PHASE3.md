# Phase 3：独立三维状态、事件时钟与Lineage

输入规范：冻结总体规范V0.1、Issue #8及2026-09-06用户Phase3实施指令。
接受基线：Phase2 `f624bf53c933f779a7e797a176ca96d3d5ce2766`。
实现仅扩展独立事件世界；不判断事件一定影响股票。价格只用fixture，不计算Price-in/Remaining Edge。

## 数据结构与入口

`states/contracts.py`声明11个Pydantic版本对象，全部复用Phase1 UTC/PIT/DerivedEnvelope：

| 对象 | 输入/输出职责 |
|---|---|
| StatePolicy | 不可变规则版本及离散阈值、观察窗、cooldown、生命周期类别 |
| EvidenceAssessment | 人工/fixture对具体事件、Evidence版本、原文片段、主张类别的核验；官方权限说明；反证解除引用 |
| SecurityPriceObservation | `(event_ref, security_id, window)`对应的价格fixture分类，保留证券明细 |
| OriginSourceSummary | 经过主张核验的支持证据子集、Phase2保守Origin/独立来源数及固定来源/簇引用 |
| DiffusionSummary | 固定窗口的来源去重、合源后Origin数、前窗来源数、来源层级、画像、编辑/删除 |
| EventPriceSummary | 仅汇总本次提供的价格观察；范围明确，不代表所有相关证券 |
| StateTransition | 旧/新状态、维度、中文原因、证据、来源摘要、规则版本、PIT信封 |
| EventClock | 实际事件起点、首次发现、实质更新及确认/反证/传播加速/市场反应里程碑 |
| EventLineage | MERGE/SPLIT/MUTATE/ARCHIVE/REACTIVATE的父/子固定版本、裁定说明和证据 |
| RecomputeTrigger | 稳定幂等键、输入引用、优先级、READY/COALESCED、最早处理时间及归并父任务 |
| EventStateSnapshot | 本次三维结论、Event版本、转换、时钟、累计核验证据及优先级 |

`StateEngine.policy/assess/register_profile/price/evaluate/lineage/pending`提供独立Python接口。
`evaluate`必须提供expected Event版本、policy版本、request_key及as_of。重复同键同输入返回原结果；
同键不同输入或过期expected_version拒绝，不覆盖新版本。输入不可知、隔离或错事件仅阻塞本次事件事务。
EvidenceAssessment需要明确人工/fixture标注；原文片段、来源身份/层级/角色、主张类别、事件关联和时间由代码核对，
不声称已自动理解文本、核验负责机构权限或解决语义矛盾。这些真实性仍是后续人工研究边界。

## 三维转换与禁止规则

机器表位于`states/reducers.py::ALLOWED/FORBIDDEN/GUARDS_ZH`。未知维度/状态永远FAIL_CLOSED；
状态对通过后仍必须满足下表的证据门槛。维度之间没有转换边，Fact reducer不接收价格/热度参数。

| 事实旧状态 | 允许的新状态（包含保持原状态） | 禁止/附加门槛 |
|---|---|---|
| UNVERIFIED | 全部已声明事实状态 | 每个目标必须有对应主张证据；不能由R3或热度自动升级 |
| PLAUSIBLE | PLAUSIBLE及更高确认状态、CONTRADICTED、INVALIDATED | 不因时间回到UNVERIFIED |
| PARTIALLY_CONFIRMED | 本状态及更高确认状态、CONTRADICTED、INVALIDATED | 不因时间退回初步可信/未验证 |
| INDEPENDENTLY_CONFIRMED | 本状态、官方确认、实施、反证、否定 | 后来合源使独立确认条件失效，转CONTRADICTED并HOLD复核 |
| OFFICIALLY_CONFIRMED | 本状态、IMPLEMENTED、CONTRADICTED、INVALIDATED | 实施需晚于已用宣布材料的新一手执行证据 |
| IMPLEMENTED | 本状态、CONTRADICTED、INVALIDATED | 时间流逝不把实施变成假 |
| CONTRADICTED / INVALIDATED | 全部事实状态，但有恢复门槛 | 未解决反证保持负向；恢复需新证据显式解除具体反证，且有后来的支持核验 |

独立确认只数支持本主张的合格一手材料：复用Phase2 `origin_summary`，新增可选证据子集过滤。
同source多个Origin只算一个独立来源；同根70转载也只能算一个；未经核验的传闻来源不增加支持计数。
UNKNOWN独立性为null/HOLD。官方一步确认需已验证S0、FACT角色、一手FACT材料、对应机构权限说明。
宣布不会自动成为IMPLEMENTED；已验证来源完整结构撤回的R5可产生CONTRADICTED，未验证来源的R5只触发P0并HOLD事实判断。
R3/R4不自动映射事实等级；新一手材料可立即触发研究，但主张未核验前仍保持原事实状态。
新有利材料不能绕过未裁定反证；归档不代表否定。Priority表示研究紧迫程度，强反证为P0。

叙事与价格允许任意已声明状态对之间跳转/降级；以下条件是机器门槛，不是无条件迁移：

| 维度 | 离散规则 | 禁止 |
|---|---|---|
| Narrative | 无窗内来源→QUIET或已有传播后的DECAY；有样本的对应主题专业画像→PROFESSIONAL_DISCOVERY；至少2传播来源→EARLY_DIFFUSION；至少3且相对前窗加速2倍→RAPID_DIFFUSION；至少5并有S1→MAINSTREAM；至少10→CROWDED；显著衰减/删除→DECAY | 粉丝数单独升级、未来画像/指标回填、把传播去重数量当事实独立确认 |
| Pricing | 已知单一观察分类→同名事件摘要；缺数据/UNKNOWN→UNKNOWN；不同Security分类有分歧→UNKNOWN/HOLD并保留明细 | 缺数据写NO_REACTION、统一套用某只证券结果、上涨升级Fact、推断剩余定价空间 |

阈值存入StatePolicy固定版本，是**未校准的离线工程初值**，不是已验证金融规律。
Source去重用于传播广度；同Origin转载仍可形成传播，但不成为多个事实根。
R1主要通过新传播进入叙事。画像按source/topic/版本及截止时点读取，sample_n=0不提供专业发现门槛，粉丝数不参与判定。
传闻可同时为UNVERIFIED+CROWDED；官方确认可同时为NO_REACTION。

### 与Phase1词表的明确边界

新StateTransition/Snapshot按本次用户指令使用QUIET、PROFESSIONAL_DISCOVERY、DECAY和LOCAL_REPRICING。
既有EventVersion继续使用冻结Phase1枚举，写入时显式转换：
QUIET→SILENT、PROFESSIONAL_DISCOVERY→EXPERT_DISCOVERY、DECAY→DECAYING、LOCAL_REPRICING→PARTIAL_REPRICING。
读取旧EventVersion反向转换；保留UNKNOWN区别于QUIET。没有放宽Phase1的内部枚举，也不重写旧历史。
本次生命周期类别在EventClock中按新指令使用VERY_SHORT/HOURLY/OVERNIGHT/ONE_TO_THREE_TRADING_DAYS/MEDIUM/STRUCTURAL/UNKNOWN。

## 时钟与PIT

EventClock保存event_started_at、first_seen_at、last_material_update_at、last_confirmation_at、last_counterevidence_at、
last_narrative_acceleration_at、last_market_reaction_at。实际起点来自显式核验的EvidenceAssessment；未知或起点有分歧时null，
不能用published_at冒充事件开始。分别计算event_age_seconds、observed_age_seconds和time_since_last_material_update_seconds。
无精确半衰期、交易日历或正式交易分钟计算；life_band是离散研究类别。

Phase2摄取仍只有初始事件或R3/R4/R5推进material时间；R1/R2/UNDETERMINED保持前值。
Phase3重算/归档不刷新material时间；新的源观察保留上一EventVersion的三维状态/生命周期，随后再显式重算。
StateTransition只在available_at<=as_of可见。新规则、指标、后来的官方否认与身份确认均只影响后续版本。
fixture：10:00传闻→10:30官方确认→11:00否认；10:15回放只有传闻。

## Lineage与任务

MERGE要求多父/一个新child，SPLIT要求一个父/多个新child，全部保留父ID和原文；child用新ID，关系与child同事务发布。
MUTATE要求本事件R4证据；可用mutated_seed改变同ID事件的DNA/标题，并追加版本。
ARCHIVE仅把新的EventVersion标为ARCHIVED。REACTIVATE要求归档后新增且属于本事件的R3/R4/R5证据；保留归档旧版。
Lineage裁定是显式人工输入，不是自动相似度合并；新关系不能回填旧时点。生命周期以EventVersion为准，Snapshot描述其引用版本的重算结论。

RecomputeTrigger支持NEW_PRIMARY_EVIDENCE、OFFICIAL_CONFIRMATION、OFFICIAL_DENIAL、R3_MATERIAL_EVIDENCE、R4_EVENT_MUTATION、
R5_COUNTEREVIDENCE、NARRATIVE_ACCELERATION、PRICE_STATE_CHANGE、CROSS_ASSET_CONFIRMATION、LINEAGE_CHANGE。
P0用于强反证/官方否认，P1用于其他实质重算，P2用于普通传播加速，P3用于无新触发的背景观察。
仅普通传播可以归并到cooldown父任务；pending按该组最新版本/输入和not_before读取，避免丢掉冷却期间新材料。
官方否认、R5和强反证绕过普通冷却；多个child各有独立幂等键。这里只给出可处理研究队列，不运行研究、LLM或外部副作用。

## Ledger增量与失败恢复

复用原SQLite五表、WAL、不可变触发器、业务事务/提交回执/publication fence；**无需DB Schema迁移或新依赖**。
Ledger仅新增Phase3 kind注册、保留输入policy_version、摄取时继承旧三维/生命周期、origin_summary可选支持证据子集。
转换/时钟/事件版本/账本项/重算触发器同事务；Lineage及child同事务。时间仍由Phase2提交后回执决定，绝不用INSERT时间替代recorded_at。
异常回滚无半条状态或child；业务已提交但回执未完成保持不可见，恢复后保守延后可用时间。HOLD和非法转移不使其他事件停止。

## 离线运行与停止点

```text
python -m pytest -q
python -m pytest -q -m pit
x-event state-fixture --db phase3-demo.sqlite --fixture configs/phase3_states.zh-CN.json
x-event schema --model EventClock
```

fixture仅允许新的独立演示库；绝不把虚构时钟混入已有研究库。Windows/Linux×Python3.11/3.12继续运行Phase1/2/3全量、PIT、三份中文fixture。
没有新增依赖/许可证；保留sgmllib3k `HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION`。
HOLD：未接真实行情、未做Live、未校准叙事阈值/生命周期、未验证24小时覆盖或金融有效性；人工语义核验仍需人工完成。
不实现Phase4产业本体、证券映射、TARGET/ALT/NULL/Red Team研究、定价空间、股票排名或交易。
不修改Market Engine、PR #2或Issue #1。独立stacked Draft PR以Phase2分支为base；Issue #8保持OPEN等待人工复审。
