# Phase 9：独立研究分级、排名与全样本机会包

接受基线：`build/x-event-engine-phase8 @ 3faa618922e6e5075a4edc3e8054a9368a1acca6`。
仅实施 Issue #14；Issue #4 为范围依据。stacked Draft PR base 为 Phase 8；不 merge、不修改 Market Engine，不进入 Phase 10。

## 唯一机器契约与 V0.1 amendment

正式存储以 `ranking/contracts.py`、策略族 `X_RANK_V0.1` 为准。复用 Phase 6/7/8 已接受的固定引用和 Gate，不重写它们。冻结 Phase0 §10–11 的正规化映射如下：

| 冻结字段 | Phase 9 唯一正规化位置 |
| --- | --- |
| candidate_id / object_id | 显式相等；成员身份由 package identity + event/security/path 固定 scope 派生 |
| grade / channel / raw_dimensions | CandidateVersion.candidate_grade / world / 有界原始维度字段 |
| path_refs / mapping_state | path_ref + positive_path_refs + negative_path_refs / mapping_state；保留各机制 |
| research_ref / red_team_ref | analysis_ref → 固定 AnalysisRun → primary/red/adjudication；decision_source 与 final_choice 原样保留 |
| research_universe_version | OpportunityPackage.request.snapshot_ref → ResearchUniverseSnapshot |
| research_rank / rank_policy_version | RankSnapshot.entries + RankVector.policy_ref → RankPolicy 固定版本 |
| execution_eligibility / execution_reasons | 固定 ExecutionEligibility；后续可选展示 overlay 不写回候选 |
| invalidation_conditions / change_from_previous | failure_conditions / CandidateChange |

不重复保存两套 grade/排序来源。公共信封沿用 DerivedEnvelope：object_id/version/as_of/computed_at/recorded_at/available_at/input_version_refs/policy_version/provenance_zh；额外保存 ranking_mode、ENGINEERING_ONLY 和恒 false 的 formal_live_alpha。截止时间是输入知识门槛，输出仍在实际完成和 publication fence 后可知。HISTORICAL_REPLAY 是新发布的历史重算，不能伪装旧 Forward 输出。

无路径、无有效身份或未覆盖的样本，event/company/path/analysis/pricing 引用可为 null，必须有显式原因；不制造占位实体或未来引用。已发布的合法候选这些引用均来自固定 Ledger 对象。非法/未来请求的根输入拒绝整次发布；已知有效 Universe 中缺下游的行仍留 WATCH/HOLD。

## 数据流与完整性

RankRequest 固定 ResearchUniverseSnapshot、声明的 MappingHistory 集合、RankPolicy、as_of、模式和可选前包。它没有 exposure/candidate 截断参数、用户持仓、偏好或 Outcome 字段。引擎展开全部指定 History 的 path；每个 Universe 决策至少保留一行，无路径证券保留 NO_KNOWN_PATH。范围外映射也保存 INVALID_IDENTITY 并单列 outside_universe_candidate_refs。

这是“固定 Universe × 声明事件范围的当前已知路径完整枚举”，不是声明已研究所有全球事件，也不是全 A 股真实暴露覆盖完成。空 history 集合是显式空事件范围，保留 Universe 的未覆盖行。RankManifest 分别报告 universe_total（证券数）和 total（path-level 样本数），不能混淆分母。

原始 Phase 6 MappingAssessment 的所有正/负/反路径保留。每个路径独立候选，同证券多个事件或多个机制都不被删除。SecuritySummary 只做展示：winner_path_ref、all_candidate_path_refs、positive/negative refs 均保留，不按有利路径覆盖不利路径。

Company 与 Security 继续分离；核对固定 Universe 决策、公司/证券/归属、路径所属 History 及 snapshot。账户没有进入这个流程。当前快照和旧图不一致需重算，不能通过固定旧身份假装当前有效。

## 研究等级与处理状态

处理状态 VALID / WATCH / OVERPRICED / REJECT / HOLD 与 candidate_grade 分开。REJECT 是核心身份/路径/研究资格不成立；数据缺失或 stale 通常 WATCH + HOLD。每个 REJECT/HOLD 有版本化 RejectReason 与具体原因，不从样本中删去。

不可配置放宽的 Alpha Gate：ECONOMIC 路径、有效正向/MIXED机制、Phase6 当前且无HOLD、选中的 TARGET/合法证券ALT 必须确实支持该路径、Phase7 MOCK_PASS 且 decision_source 非 HOLD_GATE、反方完成且不是 TARGET_INVALIDATED/NULL_PREFERRED、Phase8 ENGINEERING_ONLY、无 BLOCKING MissingDimension、Remaining Edge 非 UNKNOWN/HOLD/NONE/NEGATIVE。所有 ALPHA1/ALPHA2/BETA 必须有 countercase 和 failure_conditions。自由评论只作为研究反方/失效条件展示，不新增 FACT、不扩充 supporting_evidence_refs。

| 等级 | 当前确定性规则 |
| --- | --- |
| ALPHA1 | 上述 Gate + VERIFIED_DIRECT 暴露、HIGH/VERY_HIGH thesis、POSITIVE/STRONG edge、SUPPORTED 下一买方、LOW/MEDIUM Price-in/Crowding/Reversal、CURRENT_EVENT_DOMINANT、HIGH 已披露收入纯度、反方 UNCHANGED/合法ALT_STRONGER、无软缺口 |
| ALPHA2 | 上述 Gate + MEDIUM/HIGH/VERY_HIGH thesis、POSITIVE/STRONG 或有条件 THIN、SUPPORTED/PLAUSIBLE 下一买方、风险不超过HIGH、非强替代原因。软缺口/纯度未知/反方削弱将ALPHA1上限降到ALPHA2 |
| BETA | 明确完整分母的广泛行业扩散、相对行业反应接近中性、MULTI_CAUSE、LOW 公司收入纯度、有效研究与反方/失效条件、非NONE/NEGATIVE/HOLD edge、反转非EXTREME。不是未知项垃圾桶；edge UNKNOWN 在此允许，但不构成正式正向空间 |
| WATCH | 等待新证据/买方/定价/非核心维度，或核心未知阻止Alpha；不为了非空榜升级 |
| OVERPRICED | 有效经济研究与反方后，高/很高Price-in且NONE/NEGATIVE edge；不等于看空、SELL或做空 |
| REJECT | 无效身份/路径、非本机制正向受益、Phase7 NULL、反方致命否定等；保留审计样本 |

NARRATIVE 单独进入观察榜，只能 WATCH，保留 pricing_status=HOLD 与阻塞原因，不提供经济 Alpha 或形式上的价格救援。叙事 WATCH/HOLD 的展示位置不是正式机会资格。经济 ALPHA 与 BETA 有独立引用分组，BETA仍可在经济研究榜展示，但不冒充公司特异性Alpha。

当前 ALPHA 等级只用于 ENGINEERING_FIXTURE/MOCK_FORWARD/明确Historical工程验证，永远不是盈利概率。REAL_FORWARD 请求保留 HOLD_REAL_FORWARD_QUALIFICATION，formal_live_alpha 永远 false。

## RankPolicy 与 ordinal

策略保留 grade_order、dimension_order、ordinal_orders、unknown_policy、tie_break_policy、overpriced/narrative/missing/execution policy。所有规则条件在版本化 RankRules 或不可放宽的核心资格 Gate 内，不引入加权总分/机器学习/收益调参。

默认按处理状态、研究等级、以下词典序维度、最后稳定 (event_id, security_id, path_id) 排序：

1. remaining_edge：STRONG → POSITIVE → THIN → NONE → NEGATIVE。
2. thesis_strength：VERY_HIGH → HIGH → MEDIUM → LOW → VERY_LOW。
3. next_buyer_status：SUPPORTED → PLAUSIBLE → WEAK → REJECTED。
4. price_in：LOW → MEDIUM → HIGH → VERY_HIGH。
5. crowding/reversal：LOW → MEDIUM → HIGH → EXTREME。
6. alternative_cause：CURRENT_EVENT_DOMINANT → MULTI_CAUSE → ALTERNATIVE_CAUSE_STRONG。
7. purity：HIGH → LOW。
8. missingness：COMPLETE → SOFT_MISSING。

ordinal 仅代表有序类别的位置，完全不是胜率或收益率。UNKNOWN/HOLD/CAUSE_UNKNOWN 的 ordinal=null，单列 knowledge bucket；展示排序放在该维已知类别后，不伪装成数值0或测量最差值。Remaining Edge、thesis、buyer、Price-in/crowding/reversal 为 BLOCKING_UNKNOWN；alternative cause、纯度、非核心缺失为 SOFT_UNKNOWN。非核心缺失可降ALPHA2或WATCH，不机械全部REJECT。

收入纯度仅用固定Packet中唯一、VERIFIED/DEFINED、同Exposure的 REVENUE_SHARE；>=0.5为HIGH，其余LOW。多口径/缺值UNKNOWN；不使用利润/产能比例替代。0.5、行业广度0.6、相对行业中性容忍0.005是明确未校准工程阈值，保留于 RankPolicy，不叫最优参数，不看未来收益调整。后续校准必须新版本且经独立验收。

当日绝对涨幅不在 RankVector。经济榜和叙事榜各自从1开始排名；全样本保留所有落榜行。空正式机会榜（ALPHA1/2/BETA都0）合法；WATCH不是为凑TOP10准备的升级池。

## CandidateChange

记录前/后固定候选、from/to grade、NEW/UPGRADED/DOWNGRADED/UNCHANGED/REMOVED/REJECTED/OVERPRICED、changed_dimensions、具体reason_codes。previous_rank/current_rank/rank_change独立：等级不变而位置变化仍为UNCHANGED，不叫降级。新包可引用前包；同一package身份的version递增必须显式引用上一包，不能丢版本链。

## Current freshness 与 PIT

生成和current都复用 Phase7 ResearchStore.gates / Phase8 current，继承 Phase6 研究链、Origin、ExposureSelectionManifest、EventState及Phase8 A1语义scope与模式隔离。另检查同event的新MappingHistory、同event/security/path的新PricingAssessment、同policy_scope的新RankPolicy、固定Universe定义的新snapshot、新AnalysisRun以及收入Metric口径修订；新ID不绕过scope。缺研究/定价的候选也会检测后来首次形成的研究/定价结果。

旧包不改写；current返回原包与 RANK_RECOMPUTE_REQUIRED/HOLD，中文当前榜清空，原始全样本仍可审计。旧as_of只看到当时可知版本。Price aging继续复用Phase8，无新观察也可能触发陈旧HOLD。Historical、fixture/mock forward、real forward按既有mode family隔离，不能用Historical新对象刷新Forward。

## 执行资格与账户隔离

默认Candidate固定ExecutionEligibility=UNKNOWN。可选 AccountDisplayPolicy 仅声明 allowed_boards，单独追加 ExecutionEligibility（ELIGIBLE/INELIGIBLE/UNKNOWN）；停牌/非上市状态只影响展示资格。report(execution_refs=...)只覆盖执行展示，不能改变等级、向量或Research Rank。该overlay按自身available_at校验，不回写旧候选或旧研究排名。持仓/成本/盈亏/偏好/仓位/未来收益不能进入RankRequest或RankDimensions，严格Schema拒绝额外字段。

## 事务、Schema与兼容

所有RankVector、ExecutionEligibility、RejectReason、CandidateVersion、CandidateChange、RankSnapshot、RankManifest、OpportunityPackage在同一Ledger业务事务生成，复用提交回执/publication fence、hash、append-only触发器、幂等键与恢复；崩溃不留下半包。输出成员版本与所属package版本相同，新成员可从该package修订号开始。历史只读，旧数据不迁移/不回填。

无新SQL表、migration、依赖或许可证。Ledger/CLI仅注册新Schema；CI保留四组矩阵和全部旧步骤，增加Phase9离线演示。Phase1–8原691项测试不得修改。准确最终测试与CI证据记入PHASE9_VALIDATION.md及本次Draft PR / Issue #14。

## 工程fixture与HOLD

`python -m xevent.ranking.fixture --db <新的隔离库>` 通过既有Phase2–8接口生成虚构多事件研究/定价，再构建机会包与空榜；不手填派生Graph/AnalysisRun/PricingAssessment，不调用真实Provider。

始终标明 ENGINEERING_DEMO / NO_ALPHA_CLAIM / NO_INVESTMENT_ADVICE。
工程能力完成 ≠ 真实数据覆盖完成 ≠ 排名有效性或Alpha通过。

全部保留：HOLD_MODEL_PROVIDER_LIVE、HOLD_MODEL_USAGE_COST_UNVERIFIED、HOLD_MARKET_DATA_PROVIDER_LIVE、HOLD_PRICING_POLICY_CALIBRATION、新增HOLD_RANK_POLICY_CALIBRATION、HOLD_HISTORICAL_UNIVERSE_COVERAGE、HOLD_REAL_COMPANY_EXPOSURE_COVERAGE、HOLD_PRE_1992_CALENDAR、HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION；另有逐输入条件HOLD。

API_BUDGET=0；无真实行情/LLM/Broker API、无Bridge、无Outcome/Settlement/T+1/MFE/MAE/PnL/胜率/回测/交易执行、无Market Engine集成。Issue #14保持OPEN，PR保持Draft，完成后停止人工复审。
