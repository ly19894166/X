# Phase 10 — Shadow / Forward结算与统计验证

接受基线：build/x-event-engine-phase9 @ 6ea68d12692cd817b909b49652b76a72d95ee4c7。
对应Issue #15/#4；仅Phase10。工程结算不是真实Forward资格、Alpha成立或实盘收益。

## 输入、隔离与复用

evaluation单向读取固定OpportunityPackage、RankManifest、RankSnapshot、CandidateVersion及其输入闭包。
不重新运行Phase9来选评价样本，不修改Phase1–9对象、策略或已有测试。

LabelLedger使用独立SQLite文件，复用既有Ledger事务、append-only记录、回执、publication fence与恢复。
两个库路径相同会拒绝。源feature库通过只读历史接口读取；没有任何写回调用。
evaluation/store只在导入时注册自身Schema，不修改旧Ledger源码、SQL表或迁移。
ranking/pricing/research/graph等模块禁止import evaluation。CLI仅增加shadow分派。

FrozenFeatureArchive是label侧固定快照：保留实际完整package/manifest/snapshot/candidates，核验闭包content_hash并保存固定ID@version→hash。
跨库引用不能假装是同一Ledger本地引用：外部VersionRef由archive内的正式对象及hash证明；本地input_version_refs指向archive/plan/run及实际报价归档。
源库不包含Outcome，旧feature Ledger视图不会读取标签。任何失败/REJECT/HOLD样本均进入archive及run分母。

## 预注册与版本

EvaluationPlan冻结calendar_ref、rank_policy_ref、epoch、registration_start/end、expected_runs、六窗口、Entry/Exit价格类型、延迟与最大等待、成本、滑点、涨跌停/停牌/缺行情、样本质量、诊断网格、基线、消融、样本/簇/覆盖门槛、区间方法和seed。
计划发布不得晚于注册期开始。run必须在第一观察窗口结束及最早允许Entry之前注册。迟到不能伪装原Forward。

ResearchRunManifest保存固定计划/包/排名/Universe、feature_cutoff、package_available_at、ranking_mode、全样本数/等级数/hold数、空榜、预注册组成员、证券/事件簇、manifest_hash和epoch。
继承run_id为Ledger事务ID，shadow_run_id为业务run ID；manifest_available_at等于本对象available_at。
同包/模式/epoch重复注册拒绝；相同注册幂等键保留首次结果。当前不提供原Forward manifest改写接口，历史重算使用独立模式、新run身份。
新Plan版本必须带revision_reason；旧run仍固定引用旧版本，不跟随latest。Report不混合计划/epoch/模式，也不能遗漏该计划下截至报告时已注册的run。

## 日历与六窗口

复用MarketSession固定时间区间，以SettlementCalendar保存显式日期、闭市日、覆盖范围与资格。
V0.1仅验收UTC+8、09:30–11:30/13:00–15:00的虚构A股日历。覆盖日期不能缺失；特殊短交易日/未知日历HOLD，不猜测。

| 窗口 | 固定语义 |
|---|---|
| H30 | package可知后30个实际交易分钟，排除午休/闭市，必要时跨交易日 |
| T_CLOSE | package所属有效交易日收盘；闭市后发布则以NEXT_ELIGIBLE_SESSION所在日为T |
| T1_0935 | T之后下一交易日09:35 |
| T1_1000 | T之后下一交易日10:00 |
| T1_CLOSE / 1D | T之后下一交易日收盘 |
| T3_CLOSE / 3D | 第三个后续交易日收盘 |

14:30恰好加30交易分钟为15:00；14:45加30分钟才跨收盘累计。周末和显式节假日均跳过。
闭市后不得使用已经过去的收盘价作Entry。

## 报价、Entry和执行模拟

OutcomeQuote保存既有MarketObservation、ProviderQualification、AdjustmentBasis、MarketSession的固定归档及内容hash；保留原始时间、单位、币种、来源、复权和质量。
这些市场输入只写label库。MarketOutcomeAdapter仅Protocol，没有真实实现或网络。
嵌套固定引用/身份/provider/hash/PIT必须一致。端点采用同一证券、来源/provider、币种/单位和复权固定版本。
本阶段仅支持CNY未复权可比价格；未知FX、复权不可比、陈旧/不合格行情为HOLD，不能硬算。

Entry为package.available_at + 预注册延迟之后、第一个合法交易时段内最早发布报价；有最大等待上限。
报价价格时点不得早于该门槛，原行情available_at不得早于package，label归档不得早于run。
Exit只取精确窗口终点价格，不选最优窗口、最高价或最近的未来报价。来源冲突/同scope同时发布歧义拒绝结算。
后来修订报价只影响显式新Outcome版本，旧Outcome不覆盖。

REFERENCE_RETURN = exit/entry - 1，只描述冻结参考价格窗口。
SIMULATED_REALIZABLE另检查Entry/Exit EXECUTABLE、成交证据、正成交量、无涨跌停阻塞、T+1及行情资格。
原报价/label归档迟于观察时点超过Plan.max_quote_latency_seconds（工程默认5秒），只可参考观察，不可倒推模拟成交。
状态包括EXECUTABLE、LIMIT_BLOCKED、SUSPENDED、NO_LIQUIDITY、QUOTE_MISSING、UNKNOWN_EXECUTABILITY。
开盘涨停/一字板/跌停/盘中触板缺少可兑现证明时保守不成交，不从价格推定成交。
H30/T_CLOSE违反T+1时仅OBSERVATIONAL_OUTCOME。即使T1窗口，若Entry实际延后到同一天也不能可兑现退出。

预注册工程成本为双边commission/other_cost、退出tax、双边固定slippage；全部ENGINEERING_ASSUMPTION_UNCALIBRATED_PER_SIDE。
模拟净比率为 exit*(1-slippage)*(1-commission-tax-other_cost) / [entry*(1+slippage)*(1+commission+other_cost)] - 1。
不代表用户券商费率，无账户PnL。缺行情/停牌仍保留样本，reference与simulation分别标资格。

## Outcome与质量

Outcome仅在window.end≤as_of且全部输入已发布后产生；Ledger确保available_at覆盖计算与耐久化发布。
未到终点只保存SampleQuality=UNSETTLED / WINDOW_NOT_FINISHED，不能发布未来Outcome。
SampleQuality还区分QUALIFIED、PARTIAL、MARKET_DATA_HOLD、EXECUTION_HOLD、PIT_HOLD及原因。
late由Plan的late_tolerance_seconds确定，默认工程60秒；不伪装按时。
一次settle原子发布全样本各窗口质量/已结束Outcome。重复相同run/version/as_of幂等。
显式新版结算必须revision_reason；旧版本始终可查。崩溃遵守Ledger回滚/恢复语义。

MFE/MAE仅DIAGNOSTIC_ONLY。只有从Entry到窗口末尾的完整交易分钟网格才计算；缺网格为null/DIAGNOSTIC_GRID_INCOMPLETE。
不能用已知若干端点的最大值假装整个窗口MFE，更不能把MFE作系统收益。

## 全样本统计、相关性与消融

每个预注册窗口同时报告ALPHA1/2/BETA/WATCH/OVERPRICED/REJECT、HOLD、ALL_FROZEN以及基线/消融。
total_frozen、settled、partially_settled、unsettled、data_hold、execution_hold、pit_hold都保留。
sample_n为reference合格数，coverage_rate=reference合格/全部冻结；settlement_rate为模拟可兑现数/全部冻结。
reference统计与simulated_mean_return分开，不能将EXECUTION_HOLD的参考涨幅称为可兑现收益。
空分母输出null，空榜run参与empty_list_rate。

Event及共同Origin的连通分量在注册时按当时可知版本冻结。相同事件多证券/多path不会成为独立事件。
Origin关系展开至固定点；没有候选的中间Origin也参与传递连接，输入遍历顺序不改变事件簇。
报告candidate统计、event_cluster_n、同run重复Security/path数量，并另报各簇等权平均收益。
settled_event_cluster_n另存实际进入参考收益/区间统计的事件簇数，不能用全分母簇数冒充有效簇数。
跨run仅按各自冻结的Event/Origin tokens合并，不读取Outcome聚类；同一事件的新run不增加独立样本数。
没有Event的候选仍在全样本分母，单列unresolved_event_sample_n与HOLD_EVENT_CLUSTER_IDENTIFICATION，不计作已知/有效事件簇，不进入事件簇bootstrap。
固定seed event-cluster bootstrap对事件簇均值采样，95% percentile区间；少于两簇HOLD_STATISTICAL_INTERVAL。
默认MIN_SAMPLE=30、MIN_CLUSTER=10、coverage≥0.8，均ENGINEERING_UNCALIBRATED，非最佳参数。
不足为FORWARD_HOLD_INSUFFICIENT_SAMPLE；负结果可NEGATIVE_EDGE，Alpha1未优于基线可NO_EDGE_OBSERVED，否则INCONCLUSIVE，不输出“已验证稳健Alpha”。

基线：BASELINE_ALL_ECONOMIC_VALID取同包经济/研究有效的可评价候选，BASELINE_BETA、BASELINE_WATCH为冻结组。
NO_RANKING使用全经济有效组，不看排序。
NO_PRICE_IN为预注册资格消融：冻结经济有效、高Thesis、RedTeam非致命、SUPPORTED buyer的集合，不再按定价维度筛选；它不是改写旧grade，也不是重建未保存的模型特征。
NO_RED_TEAM与NO_NEXT_BUYER暂HOLD，不能声称已证明它们带来改善。
不做未来收益驱动调权或自动修改Prompt/Price-in/RankPolicy。

## Forward健康、模式及HOLD

ForwardHealth报告expected/created/settled/late runs、candidate/outcome数量、报价/日历/结算覆盖、stale/missing/execution hold、空榜率和PIT violation。
PIT violation>0必须HOLD。非法时间/引用请求直接fail closed；不生成虚假正常Outcome。
已注册run的未来结算请求另存EvaluationIncident并计入ForwardHealth的PIT违规数。零run时可按固定plan_ref报告缺失计划运行；不能把未运行隐去。
ENGINEERING_FIXTURE、MOCK_FORWARD、PUBLIC_PIT_RESEARCH、HISTORICAL_REPLAY、REAL_FORWARD分离。
PUBLIC_PIT使用已明确Historical来源，报告PUBLIC_PIT_REPORT；不宣称新增历史公开时间证明能力。
Historical输出HISTORICAL_RECOMPUTE，真实Forward当前注册拒绝HOLD_REAL_FORWARD_QUALIFICATION。

保留模型、模型用量、市场provider、real forward、pricing/rank校准、历史Universe、公司暴露、1992前日历、许可证正文HOLD；另保留评价策略/真实成本资格/未实施消融/样本与区间HOLD。
formal_live_alpha=false；ENGINEERING_SHADOW_READY仅在工程验收完成后可报告。

## CLI与验收

`x-event shadow register --db labels.sqlite --features-db features.sqlite --run-id ID --package-ref PACKAGE@1 --plan-ref PLAN@1`

`x-event shadow settle --db labels.sqlite --features-db features.sqlite --run-id ID --as-of TIMESTAMP`

`x-event shadow report --db labels.sqlite --features-db features.sqlite --run-id REPORT --run-ref ID@1 --as-of TIMESTAMP`

独立完整虚构fixture：`python -m xevent.evaluation.fixture --db new-labels.sqlite --features-db new-features.sqlite`。
计划/日历/报价通过严格Python Schema与Publisher预注册/导入，CLI不提供联网或账户操作。
fixture含既有Phase9完整分级/空榜、多日午休/假期；阻塞/停牌/缺行情/负结果由新增测试覆盖。
不使用fixture收益证明X有效。零新依赖，不引入pandas/scipy/机器学习/量化框架。

验收顺序：Phase10 focused → full（原777不改）→ PIT → Ubuntu/Windows Python3.11/3.12四组CI。
真实行情/LLM/Broker/API费用0；GitHub交付接口另计为工程操作。PR保持Draft，Issue #15 OPEN；不merge、不进入Phase11。
