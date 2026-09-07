# Phase 5：公司业务暴露与 PIT 研究分母

输入：Issue #10、2026-09-07 用户 Phase 5 指令、总体规范 V0.1，以及
[SPEC_AMENDMENT_COMPATIBILITY_V0.1_A1.md](SPEC_AMENDMENT_COMPATIBILITY_V0.1_A1.md)。
接受基线：`build/x-event-engine-phase4` /
`8b74a3a432da8cb6ca16781f614bd5114119585a`。

本阶段只建立公司/证券身份、公开披露知识版本、业务暴露与覆盖报告。Phase 4 A1 不变：
产业引用必须是固定 `IndustrySegment` 版本，`NarrativeTheme` 和
`ThemeIndustryRelation` 都不能充当经济暴露。没有事件选公司、Transmission Graph、
价格、Alpha、LLM、Live 或交易逻辑。

## 唯一机器契约

内部策略为 `X_PHASE5_V0.1`，继续使用 `X_EVENT_V0.1` 信封。
正式对象由 Pydantic 严格校验，拒绝额外字段、未知内部枚举和 naive datetime。
所有主要对象使用领域 ID 等于 `object_id`，版本从 1 连续追加；
关键引用固定 `(object_id, version)`，不存动态 latest。

| 对象 | 唯一事实及约束 |
| --- | --- |
| Company | 稳定经济/法律实体；法律标识、中文名、法定名、属地、经营地、有效期、身份核验和来源 |
| SecurityVersion | 证券 ID、固定公司版本、代码/交易所/板块/币种/名称、上市退市日期、ST/停牌状态 |
| CompanySecurityRelation | 固定两端版本及归属证据；关系 ID 不能更换经济端点 |
| DisclosureImport | 公司、报告期、证据版本、公开/首次接收时间、原文摘录、披露类型和人工核验 |
| CompanyExposure | 公司→固定产业→业务角色；期间、地理、直接/推断/叙事分类及映射核验 |
| ExposureMetric | 单独版本的具名指标；不把收入、利润、产能等合并为一个比例 |
| ResearchUniverseSnapshot | 知识截止点、研究定义、纳入/排除/HOLD 的固定证券版本及逐项理由 |
| CoverageReport | 研究证券分母、不同公司计数、归属/暴露覆盖及每项缺失 |

`Registry.company/security/relation`、`ExposureMaster.disclosure/exposure/metric`
是结构化写入入口；输入对应的严格 Spec，输出不可变正式版本。
`Registry.snapshot`、`ExposureMaster.coverage` 保存审计输出。
相同 ID/版本和内容幂等返回；同键不同内容拒绝；新知识追加下一版本。
这些入口不包含网络请求，也不会根据文本关键词生成已核实业务。

### 身份

公司 ID 不由股票代码或名称生成。一家 Company 的 A/H 证券使用各自 Security ID，
公司暴露只存一次。名称、代码、ST、停牌、退市变化更新 SecurityVersion，
不自动创造新公司。既有已核实法律标识不得复制成第二家公司；
改变法律标识或证券所属法律实体，不能直接宣称已核实连续性，
须使用 `REVIEW_REQUIRED/HOLD` 并另行人工核验。法律身份复杂重组自动裁决尚未实现。

`identity_status` 是领域核验状态，信封 `status` 是技术发布状态：
一条可审计发布的身份 HOLD 不等于可纳入研究。证券身份、公司或归属未确认时
隔离该证券，其他已核实证券继续。重复交易所/代码身份冲突也逐项 HOLD。

### 全 A 股 Research Universe

定义 `ALL_A_SHARE_RESEARCH_V0.1`：沪深主板、创业板、科创板、北交所 A 股，
在截止点已上市且尚未退市。ST/*ST、停牌、未知停牌状态都不作为排除理由。
H 股等证券保留主数据，但不计入 A 股研究分母。
接口没有账户权限参数；个人是否能买不能改变分母。

查询只选 `available_at <= as_of` 的知识版本，再按身份有效区间和证券日期处理。
已知的未来生效更名不会提前遮蔽现行名称；到期身份不会回退为更老身份。
今天才导入的历史名单不会出现在昨天的知识分母。
后来退市不删除历史记录；旧时点仍含当时尚未退市的证券。
证券日期按现代中国 UTC+8 日界，1992 年以前日历未验收，保留
`HOLD_PRE_1992_CALENDAR`，未新增时区数据库依赖。

本阶段只验证 fixture 和结构化导入能力，没有核验真实完整名单的入口，
所以所有快照诚实保持 `HOLD_HISTORICAL_UNIVERSE_COVERAGE`。
不妨碍有证据子集继续研究，不以工程 PASS 冒充完整覆盖。
快照本身是随后计算/提交的产物；`as_of` 是输入知识截点，
`available_at` 是快照真正发布时刻，两者不混用。

### 披露和经济暴露

DisclosureImport 的公开时间、首次接收时间取自原始 Evidence；
人工摘录必须在不可变 raw 中实际存在。报告期与实际可用时间分别存储，
报告期结束绝不赋予提前可知性。原始存档和解析复用 Phase 2，
不重新实现采集器。示例为了复用该存档接口创建虚构 Evidence/Event seed，
Phase 5 服务本身不更新 Event 或三状态。

VERIFIED_DIRECT 必须同时满足：公司身份已核实、人工核验披露、
发行/披露主体归属已核实、正式披露类别、明确公司业务映射核验、
已核实 Source，以及已校验的一手 FACT Evidence。
正式类别包括年报、半年报、公告、招股书、公司官方披露和正式核验监管文件。

Phase 2 Adapter 原本输出 `Evidence.evidence_type=UNKNOWN`，本阶段不改旧历史：
只有人工核验 DisclosureImport 明确原始正式文件类别/主体，且一手 FACT 门槛通过，
该 UNKNOWN 才能用作直接暴露材料；并不改写 Evidence 的 UNKNOWN。
直接核验摘录还必须实际出现在该合格一手事实材料中，不能借用同一包里另一条
不相关一手证据，替新闻或叙事摘录升级可信度。
已标记新闻/社交材料，或二手来源，不能走此直接门槛。
机器检查结构、来源和原文定位；业务含义与法律归属仍由具名人工核验者负责，
本阶段不声称自动审计了真实年报。

INFERRED 保留推断身份。NARRATIVE_ASSOCIATION 不保存经济产业引用。
关键词只允许 `CANDIDATE_FOR_REVIEW`，未知业务保留 UNKNOWN。
无业务披露的公司在 CoverageReport 逐项显示缺失，不需要制造空披露。

PR #21 Review 修订：本 Phase 只实现 `MANUAL_VERIFIED` 的直接核验映射。
`EXACT_ALIAS_REVIEWED / VERIFIED_RULE` 不在可接受枚举中，一律 FAIL_CLOSED；
没有实现固定 alias/rule 依据引用前不能通过声明字符串获得 VERIFIED_DIRECT。
后来的本体、alias 或 rule 修订不改写人工暴露保存的固定 industry_ref。

产业知识时间与现实时间分开：industry_ref 必须指向已发布、PIT 可知的固定版本，
其 available_at 由 Ledger 输入/提交门槛约束。现实适用性检查产业有效区间与
CompanyExposure.effective_from/to 是否重叠，使用左闭右开区间；缺失端点保持开放。
完全不相交（包括仅端点接触）FAIL_CLOSED；不会用当前墙钟判定历史业务是否合法。
报告期与业务有效区间分别保存，不能拿披露日期替换业务区间。
2025 业务可在 2026-03-28 晚披露时引用 2026-01-01 已退役的原产业版本；
旧知识时点仍不可见。

### Metric 与异常比例

指标类型分别保存 REVENUE、REVENUE_SHARE、GROSS_PROFIT、GROSS_PROFIT_SHARE、
OPERATING_PROFIT、PROFIT_SHARE、CAPACITY、CAPACITY_SHARE、PRODUCTION、
SALES_VOLUME、ORDER_VALUE、CUSTOMER_SHARE、ASSET_VALUE、UNKNOWN。

比例规范单位为 RATIO，30% 保存为 0.3，算法仅为 SAME_BASIS_RATIO；
具名分子/分母口径、期间、范围、币种和核验者必须保留。
绝对金额/数量为 REPORTED_AMOUNT，不能带比例分母。绝对负利润可保留，
不能因此生成有意义的负利润“占比”。同一 Metric ID 不允许修改指标类型、
单位、币种、范围、期间或所归属暴露。

每个实际填入的 VERIFIED 数值必须携带独立的 `numerator_source_span` /
`denominator_source_span`（绝对金额仅分子；缺失数值仍为 null）。
嵌套 MetricSourceSpan 保存原文 `quote`、原文口径 `basis_text`、
`value_text` 和数字在片段中的 Unicode 字符 `value_offset`。
Pydantic 检查口径及数字定位、完整数字边界、Decimal 等值；
engine 再检查片段确实在 evidence_ref 的不可变 raw 中。
不能把130中的30、负数中的正数或百分数直接截成所需数值。
本版仅支持原样十进制数字，无自动单位缩放、千分位或百分号转换。
数值定位提供可审计原文，具名 reviewer 仍负责公司/期间/计量口径的语义核验，
两者不能相互替代。

VERIFIED 数值还需要正式、人工核验且主体已确认的披露，以及一手 FACT + VALIDATED
Evidence；新闻、叙事、传闻、PARTIAL 或二手来源不得仅靠 reviewer 得到 VERIFIED。
这些材料可保留 SUPPORTED/HOLD，输出值为 null。各数值版本固定引用当时的 Evidence，
20/100 更正后的片段不能回填旧时点的30/100。

| 输入 | 输出 |
| --- | --- |
| 分子缺失 | null / UNDEFINED / NUMERATOR_MISSING |
| 分母缺失 | null / UNDEFINED / DENOMINATOR_MISSING |
| 分母为零或负数 | null / UNDEFINED / DENOMINATOR_ZERO 或 DENOMINATOR_NEGATIVE |
| 比例分子为负或大于分母 | null / UNDEFINED / NEGATIVE_COMPONENT_NOT_A_SHARE 或 SHARE_OUT_OF_RANGE |
| 比例口径未核实 | null / HOLD / RATIO_BASIS_UNVERIFIED |
| 指标未核实 | null / HOLD / METRIC_NOT_VERIFIED |

不从收入占比推导利润占比，不跨 MetricType 转换。语义口径的正确性依赖人工核验；
结构化字段不是机器自动从全文计算的承诺。

### PIT 与更正

现实报告期相同、知识版本不同：年报/业务暴露/指标分别追加版本。
2025 年年报在 2026-03-28 首次可知，2026-01-15 回放无该年报业务数据，
2026-03-29 才可见。4 月重述收入占比后，旧知识时点仍读原版本。

`exposure_view(as_of=...)` 返回各暴露 ID 最新可知披露版本。
已结束的报告期仍是可研究的历史事实，不按 effective_to 删除披露；
每条事实的报告期/有效期始终保留，不能解释成当前业务仍在持续。
`metric_view` 只返回仍与当前可知暴露版本一致的指标；
暴露重述后未重新核实的旧指标不会自动沿用。

## 覆盖计数

证券分母是快照中 INCLUDED 的 A 股数；公司相关计数按 company_id 去重。
H 股不会增加 A 股分母，也不会复制公司事实。
归属计数为 INCLUDED 证券的已核实公司关系数。身份被隔离的证券
在快照的 decisions/security_hold_refs 逐项保留，并报告 security_identity_hold_n。

暴露统计包括“任何类型暴露”和“经济暴露”两个数；叙事不会增加经济暴露数。
VERIFIED_DIRECT/INFERRED/HOLD 是按公司存在该类型记录计数，可能重叠，
不是互斥分桶；UNKNOWN 计数为没有任何经济暴露的公司数。
逐证券行列出固定暴露 refs、经济 refs、类型和缺失原因，可按 board 分组。
这些数仅针对当时已核实子集，不是已知全市场真实总数。
未来披露不会增加旧快照时点的 CoverageReport 业务覆盖。

中文 fixture 示例：研究 A 股 1、公司 1、归属 1、直接暴露 1、H 股排除 1；
收入占比 0.3；一月可见年报业务 0、三月可见 1。另有测试验证两个公司
仅一个覆盖时，另一个逐项 UNKNOWN，不填充业务。

## 持久化和迁移

继续使用 Phase 2 SQLite `records` 和既有提交后 receipt/publication fence。
无 SQL 表或 user_version 变更；新增八个受控记录 kind。
Ledger 仅增加模型注册，CLI 仅增加 Schema 注册和 fixture 命令。
不修改 Phase 1–4 业务逻辑、本体 A1、Market Engine 或 Market CI。

沿用已有 WAL、外键、事务 rollback、append-only 记录和提交后 available_at。
已纳入新数据的数据库须由支持 Phase 5 的代码读取；不支持旧代码降级读取新 kind。
复用旧库前应保留备份。本阶段测试包括提交前、业务提交后和回执提交后的崩溃恢复；
缺发布 fence 时不提前可见。无需新 Migration SQL。

## 验证与使用

从 `subsystems/event_engine/` 运行：

```text
python -m pytest -q tests/test_phase5_registry_exposure.py tests/test_phase5_review.py
python -m pytest -q
python -m pytest -q -m pit
x-event schema --model CompanyExposure
x-event exposure-fixture --db phase5-demo.sqlite --fixture configs/phase5_exposures.zh-CN.json
```

测试均离线，继承禁真实 socket fixture。支持 Windows/Linux × Python3.11/3.12；
实际结果另见 PHASE5_VALIDATION.md。没有新依赖；冻结锁和许可证文件不变，
保留 sgmllib3k 的 HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION。

Review 前的 fixture 数据如果缺少 VERIFIED 数值原文定位，或使用尚未实现的映射方法，
在新契约下 FAIL_CLOSED；不自动补写原文定位、不修改既有 payload。
旧数据库可用原基线作审计；本轮离线验收在新隔离库执行。尚未提供旧库自动迁移，
因此不得把已有旧版 fixture 库宣称为已完成新契约验收。

尚未验证：真实 A 股 PIT 身份全覆盖、真实公司业务覆盖、复杂法律连续性自动判断、
真实披露语义审计、Live 来源授权/采集。本阶段无网络、股票映射推理、价格、排名或交易。

**工程能力完成 ≠ 全 A 股真实数据覆盖完成。**
Issue #10 保持 OPEN，PR 保持 Draft，等待人工复审；不启动 Phase 6。
