# X Event Engine V0.1 A1：Phase4机器契约修订与兼容标准

依据：PR #20人工Review与本轮用户授权。修订前基线`82728ab8272a6468043587fec78d4eee6787a023`。
本文件是冻结总体规范§7.1/§7.2的增量amendment；不修改Phase0文档分支或旧提交。
后续Phase唯一机器契约为`ontology/contracts.py`及本A1映射表。信封schema_version继续X_EVENT_V0.1；
新记录policy_version为`X_ONTOLOGY_RULES_V0.1_A1`，兼容视图版本为`X_EVENT_V0.1_A1`。

## 1. Impact唯一规范字段

| 冻结V0.1字段 | A1唯一字段/规则 |
|---|---|
| impact_id | 显式保留，必须等于object_id；同一稳定ID只追加version，不生成第二个身份 |
| event_ref | 固定EventVersion引用，保持不变 |
| variable_type | 唯一正式PRICE；旧OUTPUT_PRICE只在显式输入兼容入口转PRICE |
| direction | UP/DOWN/FLAT/UNKNOWN；不与ImpactDirection混用 |
| scope | TARGET_MARKET/INDUSTRY_ACTIVITY/ECONOMY/UNKNOWN，表示影响覆盖层次；target_object/geography继续定义具体对象和地区 |
| magnitude_band | VERY_LOW/LOW/MEDIUM/HIGH/VERY_HIGH/UNKNOWN，研究判断，不是统计概率 |
| start_horizon | IMMEDIATE/MINUTES/HOURS/DAYS/WEEKS/MONTHS/UNKNOWN，起效时间粗分类，不制造精确时间 |
| persistence_band | MINUTES/HOURS/OVERNIGHT/ONE_TO_THREE_SESSIONS/MEDIUM_TERM/STRUCTURAL/UNKNOWN，沿冻结持续性词表 |
| inference_type | 正式字段为observation_kind=OBSERVED/HYPOTHESIS；不同时保存旧名称 |
| confidence / evidence_refs | 保留既有离散判断与固定证据引用，含义不变 |

四个新增研究字段缺省UNKNOWN，不从价格、热度或事后结果推断。scope不是ObservationBasis.scope：
后者继续表示ANNOUNCED_CHANGE等原文观察范围，二者不是同义字段。
没有估计精确幅度、持久期或开始时间；它们仍受PIT，后来判断须追加Impact版本。

`normalize_impact_input(dict)`是**显式输入边界**，返回规范ImpactSpec：
inference_type→observation_kind、OUTPUT_PRICE→PRICE。双observation_kind/inference_type一律拒绝，
即使值相同也不得形成两份输入来源。正式ImpactSpec/ImpactVariable直接提交旧名会FAIL_CLOSED。
此入口不猜未知scope、DEMAND_RISING等自由枚举，不把旧字段默认升级为已验证判断。
旧冻结最小描述如缺Phase4要求的原文核验或假设前提，也必须补足才可发布；不为兼容放宽事实门槛。

## 2. ImpactDirection固定语义

唯一枚举：**POSITIVE / NEGATIVE / MIXED / NEUTRAL / UNKNOWN**。
UNCERTAIN不是合法成员；研究不确定性使用既有uncertainty_zh、confidence、validation_status/HOLD。
UNKNOWN表示无法判断，NEUTRAL表示已声明中性，二者不可替代。
MIXED表示同一目标有实质正负机制，不等于未知或置信度低。

每条IndustryImpactCandidate保留原路径/规则方向。IndustryResolution新增industry_directions，
按同一固定industry_ref汇总；显式正/负路径并存或已有MIXED→MIXED；否则有UNKNOWN→UNKNOWN；
仅正/负（可伴NEUTRAL）→相应方向；只有NEUTRAL→NEUTRAL。不按不同产业之间的正负相互抵消。
这是声明机制的确定性汇总，不是已验证经济效果，也不计算公司或证券传导图。

## 3. 正规化来源与冻结字段的唯一映射

| 冻结字段 | 唯一正规化来源 | 固定版本导出规则 |
|---|---|---|
| NarrativeTheme.related_industry_refs[] | ThemeIndustryRelation.industry_ref | 指定theme_ref、ontology_ref和as_of内，每个relation ID选最新可知版本；仅ASSOCIATED的非空目标，去重排序 |
| NarrativeTheme.association_evidence_refs[] | NarrativeTheme.evidence_refs + 上述关系版本的evidence_refs | 固定证据版本并集，去重排序；主题初始证据与后来关系证据都保留 |
| IndustrySegment.external_crosswalks[] | OntologyVersion.crosswalk_refs所指ExternalCrosswalk | 按该对象的industry_ref与当前Segment固定版本精确相等筛选，输出crosswalk固定引用 |

ThemeIndustryRelation是独立append-only对象，包含theme_ref、ontology_ref、industry_ref或null、
ASSOCIATED/UNRESOLVED、中文机制、evidence_refs及完整PIT信封。同关系ID只能修订同一固定主题版本。
关联证据必须来自主题所引用的EventVersion；后来新Event证据需先形成新的主题版本，不能偷偷使用latest Event。
它只是**叙事关联**；即使存在相关产业，NarrativeTheme.economic_path_status仍为UNRESOLVED，
不能送入Impact→Industry经济解析替代ImpactVariable，也不声明任何真实产业暴露。

目标industry_ref必须属于指定OntologyVersion。空关系/UNRESOLVED合法；没有关联不猜测产业。
新Ontology版本不自动继承旧产业固定版本的主题关系，须明确追加对应关系。
同本体内关系后来撤为UNRESOLVED，只影响新as_of；旧关联版本仍在Ledger中。

## 4. 导出与无损round-trip

接口：`export_frozen_view(engine, theme_ref, ontology_ref, as_of=...)`。
返回严格Pydantic `FrozenOntologyView`：固定本体、冻结主题视图、冻结产业视图、原ExternalCrosswalk对象及所选关系版本。
冻结视图只在内存/JSON导出中组合字段，**不在Ledger存第二份主题行业列表或segment crosswalk列表**。
无目标的crosswalk仍保留在导出的crosswalks对象集中；不会因不能挂到Segment而丢失。

`FrozenOntologyView.model_validate_json(view.model_dump_json()).normalized()`恢复原始正规化对象，
包含全部关联证据、关系版本、crosswalk版本、原时间及hash。它是纯转换，不把导出文件写回历史库。
导出中嵌入记录的content_hash标识原正规化记录；验证该hash时先normalized()，不能把附加投影字段当成另一Ledger版本。
投影字段与正规化来源不一致会拒绝，避免接收被独立修改的冗余列表。
导出记录包含manifest中全部已知产业（包括保留的有效期信息）；业务resolver仍按有效期决定可用产业。
as_of必须覆盖每个导出记录的available_at，旧as_of不能带后来关系或crosswalk。

固定theme_ref+ontology_ref+as_of多次导出确定性一致。**仅固定本体版本而不固定as_of不足以冻结后来追加的主题关系**，
因此导出契约强制包含as_of和选中的relation_refs，不能省略知识时点。

## 5. 82728ab历史兼容与迁移边界

`project_legacy_record`只针对policy_version=`X_ONTOLOGY_RULES_V0.1`的已知历史记录：

- Impact缺impact_id时按object_id确定性补出，四个遗漏的研究字段显示UNKNOWN。
- 旧IndustryImpactRule/IndustryImpactCandidate的UNCERTAIN只投影为UNKNOWN，绝不猜成MIXED或NEUTRAL。
- 旧IndustryResolution缺industry_directions时显示空列表，不事后重算旧结论。

Ledger在检查原payload_hash之后、Pydantic模型读取之前应用此投影；**不UPDATE原业务payload、hash、回执、recorded_at或available_at**。
投影模型的content_hash按规范化模型重算，可能不同于旧软件导出的模型hash；原持久化payload_hash和原payload仍保留且先被验证。
因此跨软件修订比较旧导出文件时不能声称字节完全相同；应保留软件/policy版本并区分原存储记录与A1兼容投影。
同一A1运行时的旧as_of重放保持一致，不会获得后来新事实或填入后来研究判断。

新写入一律使用A1策略/严格Schema；不能用旧UNCERTAIN或双名称。需要正式修订旧Impact或本体时，
用原稳定ID追加新版本及新提交时间；本轮没有批量改写任何旧库。重复旧请求仍遵守既有幂等/冲突规则。
外部未知格式、未知策略版本不自动迁移，保留FAIL_CLOSED/HOLD等待明确解释。

没有新依赖、真实行业覆盖、Live、Company/Security或Transmission Graph。保留全部既有HOLD；
Issue #9保持OPEN，等待人工复审，不进入Phase5。
