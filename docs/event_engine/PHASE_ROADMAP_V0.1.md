# X Event Engine V0.1 Phase Roadmap

日期：2026-09-06；对应[总规范](X_EVENT_ENGINE_TECHNICAL_SPEC_V0.1.md)与[冻结开源矩阵](OPEN_SOURCE_REFERENCE_MATRIX_V0.1.md)。本轮只交付Phase 0文档/任务；Phase 1—11均未实施。本文件中的测试是未来必须完成的验收要求，不是已通过结果。

## 执行方式与通用完成定义

每次先核对远端分支/已有PR/Issue/CI和本地改动；重用已完成工作，不因上次中断重建。只读本规范及冻结矩阵，无明确技术阻塞不重开全网研究。每Phase一个小PR，必要时在该Issue内拆检查项，不一次性实现整个系统。默认从已审阅的事件分支/合并基线开始，不能把未合并Market PR #2默认为main。

Phase0完成后停止；后续运行须以明确Phase任务为范围。本轮不安装依赖、不开收费调用、不部署服务、不进入自动交易。阶段之间采用功能依赖，不以某个公司证据不全阻塞整个系统；真实来源/行情/API限制只标相关Live能力HOLD，fixture验收与真实验收分开。

未来PR交付必须包含：输入/输出版本、变更文件、focused tests与PIT tests原始结果、许可/依赖增量、中文示例、失败/降级原因、尚未验证事项。新增测试只覆盖本Phase领域不变量和故障，不重测库内部。共享文件未变无需重跑市场全集；如果未来确需动共享接口，运行相关回归。验收条件未满足不得关闭实施Issue或勾选完成。

`FAIL_CLOSED` 表示拒绝非法记录/发布/导出；`HOLD` 表示证据/运行或实证验收不足；`DEGRADED`允许研究继续、明确缺口。数据完整性不能软化，投资不确定性不能全变硬拒绝。

未来服务实际部署/启动由独立任务执行；Phase2提供最小采集入口，Phase7验证模型接口，Phase8验证市场数据，Phase10做真实Forward，不把“24h架构”写成已运行24h。

## 阶段概览

| Phase | 任务 | 依赖 | 本轮状态 |
|---|---|---|---|
| 0 | 恢复基线、总体规范与一次性开源矩阵 | 仓库审计 | 文档交付；草稿PR待审阅 |
| 1 | Source / Actor / Evidence / Event 核心Schema | P0 | 未开始 |
| 2 | Event Ledger、Origin去重、Novelty与最小采集入口 | P1 | 未开始 |
| 3 | 三状态机、事件时钟及版本/合并/分裂/复活 | P2 | 未开始 |
| 4 | Impact Variable 与 X产业本体 | P3 | 未开始 |
| 5 | Company Exposure Master 与全A股Research Universe | P4 | 未开始 |
| 6 | 事件→产业→A股 Transmission Graph | P5 | 未开始 |
| 7 | GPT结构化研究、TARGET/ALT/NULL与Red Team | P6 | 未开始 |
| 8 | Market Recognition / Price-in / Remaining Edge | P7 | 未开始 |
| 9 | α1/α2/β/WATCH/OVERPRICED/REJECT与独立排名 | P8 | 未开始 |
| 10 | Shadow / Forward结算与统计验证 | P9 | 未开始 |
| 11 | 与X Market Engine建立可选只读接口 | P10 | 未开始 |

## Phase 0：恢复基线、总体规范与一次性开源矩阵

- **输入**：当前main/开发分支、commits、PR/Issue/CI及四份协议完整讨论。
- **输出**：RECOVERY_REPORT、总体技术规范、冻结开源矩阵、本路线图、独立文档草稿PR和实施Issues。
- **数据结构**：文档版本、审计SHA/日期、模块复用分类、每Phase验收契约。
- **单元测试**：本Phase不写运行代码，不增加形式化单元测试；检查四协议覆盖、交叉引用、Phase 0—11字段及仅新增文档的diff。
- **PIT测试**：文档审查晚到公告、更正/合并历史、模型晚完成、公开PIT与Forward隔离用例；这是设计审查，非运行PIT PASS。
- **验收条件**：五项本轮交付可在GitHub回读；原PR #2、Issue #1和代码不变；开源决策有固定提交/许可依据；后续任务可单独执行。
- **FAIL_CLOSED / HOLD 条件**：仓库/原讨论不能访问则标明缺口；文档冲突未解决或远端写入未验证不得声称完成；不以旧CI替代新事件验证。
- **允许范围**：docs/event_engine/，本轮仅文档。

## Phase 1：Source / Actor / Evidence / Event 核心Schema

- **输入**：已审阅的Phase0规范、冻结Pydantic/pytest复用选择、无网络fixture。
- **输出**：独立subsystems/event_engine包、最小x-event CLI入口、严格模型/枚举和生成JSON Schema；中文字段说明及错误解释。
- **数据结构**：公共VersionEnvelope、Source、SourceTopicProfile、Actor、ActorTopicProfile、Statement、EvidenceVersion/Relation、EventVersion、EventDNA；为后续对象保留版本引用。
- **单元测试**：合法/非法枚举、未知数值、前导零、带时区时间、人物×主题、事实/意图/传闻分离、JSON round-trip、引用形状；只测X契约。
- **PIT测试**：naive时间拒绝、available_at晚于as_of拒绝、公告effective早而available晚、人物任期后来变更不可提前、LIVE与PUBLIC_PIT模式不可混用。
- **验收条件**：可离线生成/校验一份source→evidence→event fixture；Schema冻结且一致；独立安装不依赖xalpha；锁稳定包版本/许可清单并加独立CI。
- **FAIL_CLOSED / HOLD 条件**：关键时间/身份/引用不合法则隔离记录；Schema不一致阻止持久化；原始业务占比未知可null，不能强行补数字。
- **允许范围**：subsystems/event_engine/{pyproject.toml,src/xevent/contracts,tests,configs}；必要时新增独立CI文件，不改原CI语义。

## Phase 2：Event Ledger、Origin去重、Novelty与最小采集入口

- **输入**：P1契约、固定事件/转载/编辑fixture；选定HTTPX/feedparser/Tenacity/SQLAlchemy。
- **输出**：SQLite事务Ledger、不可变原始证据档案、来源游标、幂等写入/outbox、Origin簇与R0—R5分类；官方/RSS最小适配器和replay入口。
- **数据结构**：EventLedgerEntry、EvidenceChange、OriginClusterVersion、NoveltyDecision、CollectorCursor、OutboxJob、SourceHealth；记录raw与normalized哈希。
- **单元测试**：1源20媒体50转发仍1 origin；精确重试不重复；相似但不同政策不误并；编辑删除追加；中途崩溃/事务回滚/恢复不半写；mock超时和429有限退避。
- **PIT测试**：晚到旧文不改first_seen/available；旧时间看不到后来编辑；同源后来识别不得回写过去独立来源数；游标恢复保留真实接收时刻。
- **验收条件**：无需LLM可fixture→证据→事件→账本再replay；重复运行得到相同逻辑结果；source失败只降级该源；可一次性手动读取已配置公共源但不需购买权限才能过离线门。
- **FAIL_CLOSED / HOLD 条件**：原始哈希不符/事务一致性失败停止该发布；无法取源记SOURCE_UNAVAILABLE；来源时间语义未验收仅replay/当前观测，不伪称历史或24h覆盖。
- **允许范围**：src/xevent/{evidence,ledger,discovery,adapters,runtime}、tests、migrations、configs（均在独立子系统内）。

## Phase 3：三状态机、事件时钟及版本/合并/分裂/复活

- **输入**：Ledger、R0—R5、截至时点的事实证据/传播统计/价格fixture。
- **输出**：独立事实/叙事/价格reducer、hazard clock、事件lineage、受影响重算队列；P0/P1反证优先调度。
- **数据结构**：StateTransition、EventClock、EventLineage(MERGE/SPLIT/MUTATE/ARCHIVE/REACTIVATE)、RecomputeTrigger；事件价格摘要与security价格状态分开。
- **单元测试**：传闻热度高不确认事实、官方一步确认、实施需新证据、反证降级、价格升不升事实、归档复活、merge/split保留原ID、重复触发幂等、冷却不延迟强反证。
- **PIT测试**：as-of重建合并前/后不同视图；未来否认、复活、新阈值不进过去；模型/指标晚到只在后续版本生效。
- **验收条件**：有显式状态转换/禁止转换表及中文原因；三维独立；历史按版本可复现；事实衰减不自动变为假；未知价格不写无反应。
- **FAIL_CLOSED / HOLD 条件**：缺支持证据不得升级相关状态；矛盾未裁定转CONTRADICTED或HOLD该研究；账本非法转移拒写，不停全部正常事件。
- **允许范围**：src/xevent/states、discovery、runtime和对应tests。

## Phase 4：Impact Variable 与 X产业本体

- **输入**：事件版本/确定性fixture、本规范标准影响变量与产业/主题分离规则。
- **输出**：影响变量标准化、独立产业树/alias/crosswalk、主题实体；Impact→产业候选解析。
- **数据结构**：ImpactVariable、IndustrySegment、NarrativeTheme、OntologyVersion、ExternalCrosswalk；OBSERVED/HYPOTHESIS分离。
- **单元测试**：DEMAND+UP唯一存储方式、FX币种方向必填、未知同义词拒绝、产业循环检测、主题不能冒充产业、铜供应少与铜价高不是同一事实。
- **PIT测试**：产业归属/crosswalk修改只追加；当前行业分类不能回填历史；晚到字典/证据只从可知时生效。
- **验收条件**：同输入同本体版本确定性结果；每映射有中文机制；可以同时导出正负影响产业；不存在无限自由文本枚举。
- **FAIL_CLOSED / HOLD 条件**：未解析产业保留UNRESOLVED，不能猜；仅对应主题则走叙事通道；身份/版本引用错则隔离。
- **允许范围**：src/xevent/ontology、contracts及独立configs/fixtures。

## Phase 5：Company Exposure Master 与全A股Research Universe

- **输入**：PIT证券/公司身份来源或fixture、公开披露证据、X产业本体；现有market契约仅作只读参考。
- **输出**：公司/证券分离的PIT主数据、公司业务暴露库/索引、全A股研究分母与覆盖报告、披露导入/人工校核入口。
- **数据结构**：Company、SecurityVersion、CompanyExposure、ExposureMetric、ResearchUniverseSnapshot、CoverageReport；业务/地理/角色/期间/占比分母。
- **单元测试**：A/H多证券、更名退市、六位代码、生产者/消费者、收入/利润/产能不可互换、零/负利润分母、主板/科创/创业/北交/ST/停牌保留、未知暴露显式缺失。
- **PIT测试**：年报次年公开不得回填上一年；重述同现实区间选知识版本；今天名单不能作历史Universe；后来退市股票仍在过去样本。
- **验收条件**：完整研究身份范围按PIT来源报告，暴露未覆盖逐项显示；无需先补齐全市场业务才可研究有证据子集；不得过滤执行不可用股票。
- **FAIL_CLOSED / HOLD 条件**：证券身份无法核实隔离该候选；历史主数据不足则历史评估HOLD，当前可核实公司继续；暴露未知不能VERIFIED_DIRECT。
- **允许范围**：src/xevent/exposures、registry、contracts、migrations、tests；不修改xalpha/security_master.py。

## Phase 6：事件→产业→A股 Transmission Graph

- **输入**：Event/Impact/产业、PIT公司暴露与证券、事实及市场关联证据。
- **输出**：有限深度Path Builder、经济/叙事双路径、公司净影响状态、替代标的检索；股票反查相关活跃事件。
- **数据结构**：EdgeVersion、TransmissionPath、MappingAssessment、MappingHistory；positive/negative/narrative路径引用及economic_depth。
- **单元测试**：铜生产者正向、耗铜企业负向、综合企业MIXED；名字像但无证据拒绝；N1不可升级L1；edge/node连续性、循环、悬空引用；原始多路径不粗暴加减分。
- **PIT测试**：每条关键边/暴露引用满足as_of；未来映射修正不覆盖旧候选；多事件同源不重复加权；证券映射按当时版本。
- **验收条件**：能展开完整经济链或合法叙事链；每关键业务事实有定位；超过3经济层软降级；候选可单独查看最强反路径。
- **FAIL_CLOSED / HOLD 条件**：无合理路径/核心映射被证伪拒绝对应路径；未验证机制可PLAUSIBLE；缺任意关键事实证据不能VERIFIED_DIRECT，保留研究线索。
- **允许范围**：src/xevent/graph、exposures、contracts、tests。

## Phase 7：GPT结构化研究、TARGET/ALT/NULL与Red Team

- **输入**：PIT ResearchPacket、候选路径、价格fixture、冻结结构化输出参考；模型接口mock优先。
- **输出**：模型provider适配、证据预注入、主分析/反方/有限裁定、缓存与预算、引用及数值验证、中文研究报告。
- **数据结构**：ResearchPacket、HypothesisSet、RedTeamReport、AnalysisRun、CostLedger、ModelConfig、SearchCoverage、PromptVersion。
- **单元测试**：TARGET/ALT/NULL齐全；用户持仓/喜好变化不影响研究输入/排名；杜撰引用或财务数字拒收；提示注入隔离；1主+1反+必要1裁定上限；缓存、超时/额度耗尽和结构修复有界。
- **PIT测试**：检索/工具/记忆均统一as_of；未来结算经验禁止；14:50开始14:52完成不可导出到14:50；公共历史重算与真实Forward分开。
- **验收条件**：mock可完整演示，并用可用provider做有预算的有限验收后另报LIVE状态；每正式推荐有具体反方/失败路径/替代者搜索，未找到不编造；不引入整套框架。
- **FAIL_CLOSED / HOLD 条件**：无API访问/预算仅Live分析HOLD，mock契约可验收；反方未完成不得发布新α1/α2/β；输出非法只隔离该结果，旧结果带时间保留。
- **允许范围**：src/xevent/research、adapters、runtime、tests；模型和提示词版本化，不硬编码未经验证API型号。

## Phase 8：Market Recognition / Price-in / Remaining Edge

- **输入**：PIT研究/图、合格行情与基准、传播/行业广度、跨资产观察、交易日历；fixture先行。
- **输出**：异常收益/量额/行业扩散确定性计算、认知/定价/拥挤/新增买方/剩余生命/空间/反转风险独立评估。
- **数据结构**：MarketObservation、BenchmarkSnapshot、PricingAssessment、NextBuyerHypothesis、NonReactionInvestigation、AlternativeCauseSearch、MissingDimensions。
- **单元测试**：涨幅不等于定价；剩余不等于100减已定价；同时间量基准；UNKNOWN不同于0/无反应；高认知低反应调查；上涨排查其他事件；闭市价格显陈旧；跨资产币种对齐。
- **PIT测试**：固定公开/first_seen锚点含证明、事件前趋势窗不越界；beta训练只用事前；盘中不能用日终总量；复权/行业成分/跨资产接收时间守门。
- **验收条件**：每候选保留原维度、数值/分母/窗/来源；可解释剩余空间分级，无假精确百分比；provider时间/单位资格与研究判断分别验收。
- **FAIL_CLOSED / HOLD 条件**：不可比价格或所有价格缺失保留映射但定价UNKNOWN，正式剩余空间判断HOLD；部分跨资产缺失软降级；系统性单位/时钟错阻止定价发布。
- **允许范围**：src/xevent/pricing、adapters、contracts、tests。

## Phase 9：α1/α2/β/WATCH/OVERPRICED/REJECT与独立排名

- **输入**：图/研究/Red Team/定价、PIT Research Universe、可选账户资格策略。
- **输出**：版本化中文机会包、经济与叙事分榜、变化说明、只用于展示的执行资格、稳定排序策略及原维度导出。
- **数据结构**：CandidateVersion、OpportunityPackage、RankPolicy、ExecutionEligibility、CandidateChange、RejectReason；处理状态与研究等级分离。
- **单元测试**：β可入榜但不冒充经济；真假受益与已定价分别判；过度定价不等于看空；持仓变化/执行不许可不改研究rank；缺纯度软降级；同分稳定；空榜和全样本保留。
- **PIT测试**：仅截至发布时可用输入；后来的价格、账户条件、阈值、模型不可回填过去候选；引用固定版本，可复现每次升级降级。
- **验收条件**：所有α1/α2/β有反方和失效条件；明确排序ordinal/UNKNOWN策略；工程分级不叫盈利概率；统计空榜/覆盖和拒绝原因，防过度过滤。
- **FAIL_CLOSED / HOLD 条件**：PIT/伪造/无效身份结果隔离；未完成RedTeam的新正式推荐HOLD；合理风险不一票否决；不能为有榜单而强行补证据。
- **允许范围**：src/xevent/ranking、contracts、CLI/report模板、tests。

## Phase 10：Shadow / Forward结算与统计验证

- **输入**：不可变机会包/全样本manifest、PIT行情、交易日历、预注册评估计划；观察期真实累积数据。
- **输出**：30交易分钟/收盘/次日开盘09:35与10:00/1日3日结果；可兑现模拟、分层统计、基线/消融、Forward健康与HOLD报告。
- **数据结构**：ResearchRunManifest、Outcome、EvaluationPlan、EvaluationReport、SampleQuality；labels与features隔离。
- **单元测试**：T+1限制、涨跌停不可成交、停牌/缺行情、费用滑点、MFE不作收益、全部失败样本分母保留、事件簇相关样本合并/分组统计。
- **PIT测试**：严格特征/Outcome访问隔离；评估窗终点已发生且结果可用；按时间向前/事件簇切分避免泄漏；晚结算经验不回流旧研究；PUBLIC_PIT与Forward分报。
- **验收条件**：结算器fixture可验收与真实Forward资格分开；预注册样本期/指标/成本/阈值，报告样本量、区间、覆盖/空榜率、基线与负结果；无收益承诺。
- **FAIL_CLOSED / HOLD 条件**：市场数据/时间语义不合格、样本不足、区间不足支持稳健Edge则Forward HOLD；不得为过门挑窗口或删除失败；离线测试通过仍不等于Alpha成立。
- **允许范围**：src/xevent/evaluation、tests、版本化评估配置/报告，不改旧market标签。

## Phase 11：与X Market Engine建立可选只读接口

- **输入**：独立事件机会包/manifest、经核实的Market Engine接口及当前真实验收状态；不依赖PR #2必须合并才能完成前10阶段。
- **输出**：版本化只读导出/reader；市场侧可按自身decision_ts读取已经实际完成的事件特征；事件引擎无market也可运行。
- **数据结构**：EventFeatureSnapshot(event/candidate版本、available_at、as_of、schema_version、provenance)、AdapterCompatibilityReport、只读契约。
- **单元测试**：禁写market数据库/模型/账户；不开自动交易；拔掉market仍运行；接口断开不影响上游；三尾盘时点只是consumer查询，非事件调度；A=量价/B=量价+事件比较入口。
- **PIT测试**：每个导出字段/input及模型完成时间均<=market decision_ts；不得用14:52结果补14:50；consumer自己重验PIT，schema不兼容拒收。
- **验收条件**：只读集成fixture成功、独立性回归通过；涉及旧代码仅另列最小增量PR并测试；真实live集成需旧market数据验收解除其相关HOLD。
- **FAIL_CLOSED / HOLD 条件**：Market Engine仍HOLD/未合并/不可用不阻止事件独立研究，只阻止真实联调PASS；导出时间或版本不合格FAIL_CLOSED，不自动放宽旧策略。
- **允许范围**：src/xevent/adapters/market_engine、tests、docs；不得顺手合并PR #2或改旧目标。

## GitHub实施任务索引

发布时补充实际Issue链接；避免猜测编号。每个Issue包含本Phase的全部执行字段与依赖。总任务负责跟踪，不自动触发所有Phase。

