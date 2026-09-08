# Phase 7：固定证据研究、TARGET / ALT / NULL 与独立反方

基线：`build/x-event-engine-phase6 @ f58b8f869af99c9196480f7be5c5aa50970ff0b5`。
本阶段只交付结构化研究工程；不修改 Phase1–6 业务逻辑，不实现 Phase8 或交易。

## 输入规范与本阶段兼容说明

输入为冻结 V0.1 §8、Issue #12、Phase6 A1 以及本轮用户的 Phase7 完整指令。最新明确范围优先：本阶段从合法 MappingHistory 构建 ResearchPacket；这是已建图上的结构化研究，不改写早期事件发现/映射流程，也不引入价格fixture或排名。

冻结文本中的“至少一个ALT”按本轮“不编造替代公司”要求落实：ALT列表可以为空，但必须具名记录查询范围/缺口。NULL始终是不可删除的一等假设。不得仅为凑齐数量添加公司。

HypothesisSet、RedTeamReport、Adjudication 是独立导出 JSON Schema 的结构化结果，正规化存于固定 `ModelResult` 版本中；完整引用为 `(ModelResult object_id, version, result field)`，具体假设再加 hypothesis_id。AnalysisRun 的 `final_result_ref + final_hypothesis_id` 是固定最终指针，不使用动态 latest。

## 正式对象和存储

- PromptVersion：同一固定版本内包含 PRIMARY、RED_TEAM、ADJUDICATION 三份模板。不可变系统安全规则由程序附加，证据无修改权限。
- ModelConfig：provider/model标识、temperature、输出额度、超时、一次结构修复限额、请求/输出预留预算、Prompt固定引用。
- SearchCoverage：实际事件证据、第一手来源、Origin与可核实独立来源数量、正负叙事路径数、真实暴露覆盖HOLD、关键缺口和固定包查询范围。
- ResearchPacket：完整事件/状态/图/评估/清单、正负叙事反路径、公司/证券、证据/Origin、可用Metric、Prompt/ModelConfig/SearchCoverage固定引用、hash、as_of及全部输入可用时间。
- HypothesisSet：TARGET对象、ALT列表、NULL对象、selected_id；每项保留支持/反方引用、假设、失效条件、未知、研究置信度带和简短结论依据。
- RedTeamReport：独立挑战、失效条件、证据/反路径、结构化结论与建议假设。
- NumericClaim：具名Metric类型、数值、单位/币种、固定Metric引用和分子/同口径比率定位方式。
- ModelResult：单角色经校验的公开结构化结果、响应摘要和缓存键。
- CostLedger：调用前RESERVED、完成或失败后追加下一版本；记录请求/预留输出、实际用量（若返回）、超时、修复、cache及状态。统计需取每个调用ID的最新版本，不能把预留与完成版本重复计数。
- AnalysisStart / AnalysisRun：开始前耐久化身份、完成后的公开审计状态、全部调用/结果固定引用、最终选择、实际开始/完成/可用时间。

所有正式对象复用 Phase2 SQLite records、事务、提交回执和 publication fence。没有新SQL表或迁移。Ledger/CLI仅新增类型注册；旧481测试不改。

## ResearchPacket与freshness

只接受固定 MappingHistory / ModelConfig 和截止点；没有新闻自由输入、持仓、成本、偏好、账户资格或后验收益参数。通过图输入闭包取得可追溯事实，通过Phase5 metric_view选择该暴露对应、截止点最新可知指标。任意Packet外证据和未来对象不可加入。

复用 Phase6 ResearchKnowledge / path_reasons；检查事件、状态、影响及前提、解析、候选、暴露/完整选择、公司、证券、归属、Universe和Origin。History自身新版也需重算。State缺失或不对应固定EventVersion、CONTRADICTED/INVALIDATED/ARCHIVED都会进入研究Gate。

默认拒绝不完整图；显式 `allow_degraded=True` 可以形成 REVIEW_ONLY 包。它只能保留降级研究/NULL，不能发布正式TARGET。分析开始和最终发布前重复freshness检查，运行途中出现的新证据也不能被模型豁免。范围外真实覆盖HOLD保留，可靠已知子集仍可研究，不要求先补齐全市场。

## 主研究、反方与有限裁定

Primary不读取Red Team，Red Team以独立系统模板接收同一个Packet和已完成Primary公开结果；没有共享隐藏聊天历史。反方必须带挑战、失效条件和全部已知反路径，可选择 TARGET_WEAKENED / TARGET_INVALIDATED / ALT_STRONGER / NULL_PREFERRED / UNCHANGED。

角色分离不证明统计独立或真实模型有效。Mock只验证工程规则。默认一次Primary、一次Red Team；只有重大分歧才最多一次裁定，无分歧不调用。TARGET_INVALIDATED不能被无新事实的裁定复活；不允许无限辩论。结构修复最多全run一次，单独记retry且仍消耗预算，默认关闭。

TARGET/替代公司ALT需要本事件合法经济正向或MIXED路径及对应公司证券；叙事路径不能升级。ALT也允许不指定公司/证券的替代经济解释，仍必须引用本事件合法经济路径，可引用负向机制，并保留全部已知反路径；它不代表推荐另一家公司。各公司全部已知负向路径必须列入反方。不同公司的ALT复用Phase6 alternatives并明确history/event/candidate作用域。NULL合法，缺替代者记录缺口；不存在BUY/SELL、目标价、涨幅、仓位或Alpha评分接口。

## 引用与数值

所有支持/反路径和Evidence都必须在Packet指定集合内，且公司、证券及路径一致。不能将Packet另一维度的任意Evidence充作所引路径支持。CONFIRMED_FACT/COUNTEREVIDENCE只允许已校验FACT Evidence原文精确摘录；自由推理是模型假设，不是新增事实核验。

NumericClaim只开放Phase5已VERIFIED、DEFINED的ExposureMetric：数值、metric_type、单位、币种精确匹配；REPORTED_NUMERATOR核对分子原文，SAME_BASIS_RATIO同时核对分子/分母不可变raw定位。复用Phase5对零/负分母和口径门槛，禁止收入占比改成利润占比、比例改成百分数或缺源数字。

尚未支持任意网页数字提取与单位换算，未受支持声明拒收为 INVALID_NUMERIC_CLAIM / NUMERIC_CLAIM_UNVERIFIED。数值不得藏入自由总结；模型文本的有限词法检查只是附加防线，不能声称已实现通用事实理解、完整自然语言注入识别或真实研究真实性验证。

## 提示注入及响应审计

系统GUARD、角色模板、输出Schema和工具权限由代码控制。外部原文仅位于 `untrusted_data` JSON数据区；Provider接口没有工具执行、浏览、持仓记忆或系统角色覆盖入口。模型输出额外字段、虚构引用和越权交易结论拒收，结构修复也不能改变规则。

只持久化通过严格Schema的公开结果与原响应hash。非法响应只记录hash和错误类别，不存其任意字段、异常消息或私有思维链。这是对早期“原始响应审计区”的保守实现：避免将响应中的隐藏推理/密钥持久化；不声称可从hash恢复原响应。Provider不接收或产生隐藏思维链协议。真实Provider的语义注入防护仍未Live验证。

## Provider、超时、预算和缓存

ModelProvider是最小同步协议。当前只有MockModelProvider；配置不硬编码任何未经验证的真实API型号，不查找密钥、不联网。未来真实接入需单独授权及验收，当前返回 HOLD_MODEL_PROVIDER_LIVE。

标准库worker最多一个在途，受有界Semaphore限制；超时发取消信号，未响应取消的Provider占用槽位期间拒绝新调用，不无限创建后台线程。Mock协作取消；真实Provider必须自行使用传入timeout并实现取消。没有asyncio网络自管道，因此不放宽旧离线socket禁令。线程隔离不是任意恶意Provider的进程沙箱，真实Provider尚未验证。

每次请求先耐久化预算预留。max_requests默认三次、最大四次（含最多一次结构修复）；每次按max_output预留输出额度。Provider返回用量则记录并核对输出限额；未返回为null，实际token/cost保持HOLD_MODEL_USAGE_COST_UNVERIFIED。没有可信单价时，配置货币上限会HOLD_COST_PRICE_UNKNOWN，不能假装满足金额预算。缓存命中不产生请求。

缓存键包含Packet hash、research_mode、Prompt及ModelConfig内容hash、角色、该次输入（含上游模型结果）和Schema/系统规则。新证据/新图/新配置/新包不能静默命中旧缓存；只复用已验证结果，旧缓存仍保留历史时间。

研究身份在调用前写AnalysisStart。相同run重复请求幂等；发现旧Start但缺最终Run时，记录HOLD_INCOMPLETE_PREVIOUS_RUN，不盲目重新调用。旧的有效阶段结果仍存在；恢复不是Provider exactly-once保证，也不自动继续收费调用。

## PIT与模式

Graph和原始事实、Prompt/ModelConfig须在packet.as_of可知；SearchCoverage/Packet本身是在实际构建完成后发布的新派生物。ModelResult/AnalysisRun同样使用Ledger真实提交完成时间，不能把as_of当输出可用时间。开始/完成时间保留用于审计；14:50开始14:52完成的模型结果在14:51不可见。

`research_mode=MOCK_FORWARD` 使用当前freshness检查；`HISTORICAL_REPLAY`只用历史截止知识并隔离cache，但历史重算的输出仍在今天实际完成后才可见，绝不模拟提前发布时间。底层mode=LIVE_FORWARD指本机真实观测/提交记录；Packet、ModelResult、AnalysisRun均携带research_mode，并在is_visible的LIVE_FORWARD查询中拒绝Historical对象，只允许按真实发布时点的OBSERVED_REPLAY读取。Ledger.history是原始审计接口，不是Forward资格筛选；Historical结果不得作为Forward研究成绩。未实现PUBLIC_PIT模型时延模拟或未来结算记忆。

## 离线使用与HOLD

```text
python -m xevent.research.fixture --db new-phase7-demo.sqlite
x-event schema --model ResearchPacket
x-event schema --model HypothesisSet
python -m pytest -q tests/test_phase7_research.py tests/test_phase7_pit.py
python -m pytest -q
python -m pytest -q -m pit
```

报告由正式AnalysisRun/ModelResult构建，显示输入截止、实际可用时间、假设集合、反方结论及HOLD，默认演示综合公司被反方推翻后选择NULL。

持续保留历史Universe、真实CompanyExposure、1992年前日历、sgmllib3k再分发正文、Live模型、真实模型用量/成本等HOLD。工程MOCK_PASS不代表真实模型有效、真实Alpha成立或实盘可用。无新依赖、无新许可证；不修改Market Engine；PR保持Draft，Issue #12 OPEN，人工复审前停止，不进入Phase8。
