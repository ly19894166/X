# X Event Engine Phase 1：离线核心契约

输入基线：`X_EVENT_V0.1`，Phase 0 已人工审阅的提交
`0a5469a0b90c9302ebb3889e1088486404bd87bb`，Issue #6。
遵循 `docs/event_engine/` 的总体规范、Roadmap 和冻结开源矩阵。
本包只建立领域类型、离线引用校验和 CLI，不依赖 `xalpha`。

## 安装与离线使用

支持目标：CPython 3.11/3.12，Windows x64 / Linux x64；四组环境由独立 CI 验证。
在本目录使用独立虚拟环境，避免影响 Market Engine 环境：

```powershell
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install --require-hashes --only-binary=:all: -r requirements.lock
.venv/Scripts/python.exe -m pip install --no-build-isolation --no-deps -e .
.venv/Scripts/x-event.exe ingest --fixture configs/offline_fixture.zh-CN.json
.venv/Scripts/x-event.exe inspect --fixture configs/offline_fixture.zh-CN.json --event-id EV_001 --as-of 2026-09-06T10:00:03+08:00
.venv/Scripts/x-event.exe schema --model EvidenceVersion --output schema-output.json
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest -q -m pit
```

Linux 用 `python3.11 -m venv .venv`，对应可执行路径为 `.venv/bin/python` 和 `.venv/bin/x-event`。
首次安装需要获取指定发行包，所有业务命令及测试使用本地虚构 fixture，不访问新闻或模型 API。
`ingest` 在 Phase 1 仅校验内存中的文件，不代表已入库或完成真实耐久化。

样例原文：“【虚构离线样例】机构拟研究新增算力供电试点；尚未实施，不能视为已确认订单。”
完整 fixture 含 9 个版本：来源、人物、证据、发言、事件、来源主题画像、叙事画像、人物主题画像、证据关系。
发言保留 `INTENT`，事件保持 `UNVERIFIED`，价格与叙事状态 `UNKNOWN`。
10:00:03 查不到尚未可用的事件，10:00:08 才能读取样例事件版本。

CLI 退出码：`0` 校验成功/已输出；`2` FAIL_CLOSED（输入、时间、引用、哈希、文件或参数错误）；
`3` HOLD（截止时点无可见事件）。退出失败时不输出合格结果。
没有 `run`、网络采集、后台服务或交易命令。

## Schema 与中文字段口径

| 契约 | 含义与核心约束 |
|---|---|
| VersionEnvelope | 每个业务版本的公共信封；对象/版本、输入/证据引用、运行/策略、真实可用与有效区间、状态/原因、内容摘要 |
| Source | 来源身份、层级、用途、采集方式和留存策略；条款/授权/允许用途/原文留存/访问限制是独立元数据 |
| SourceTopicProfile | 来源 × topic_id 的可信、专业、影响、扩散分级及领先统计；不设单一永久总分 |
| NarrativeSourceProfile | 主题作用域的大V画像；followers 粉丝数、originality 原创占比、citation_rate 引用占比、领先/跟随/后验解释/编辑/删除统计 |
| Actor | 人物或机构、组织引用、职位任期及已核验账号版本；职位现实有效期与知识可用期分开 |
| ActorTopicProfile | 人物 × 主题权威/专业/影响；发言样本、兑现、部分兑现、否定、未解决计数与结果最晚可知时间 |
| Statement | 发言人/来源/主题、场景原始类型、事实/意图/预测/意见/传闻/叙事、政策确定性与冲击潜力分开 |
| EvidenceVersion | 来源版本、原文定位/语言/摘要、首次文本、origin 待识别标识、一手性/独立性/主张类别、来源与系统时间、质量状态 |
| EvidenceRelation | 对具体发言或事件版本的 SUPPORTS/CONTRADICTS/CONTEXT，保留原文片段与中文解释 |
| EventVersion | 事件身份、标题/DNA、具体证据版本、三种独立状态、优先级、生命周期、修订原因；不执行状态转换 |
| EventDNA | 主体版本、行动、事件客体、目标实体、领域、地域、时间范围及身份规则版本；不是证券代码或概念股标签 |

统一使用公共 `version` 表示规范中的 `event_version`；公共证据版本引用字段统一为 `evidence_refs`。
DNA 的 `actor_refs` 是规范 actor_ids 的固定版本形式，object/target 实体结构同时携带类型和中文名称。
`hypothesis_set_ref` 仅预留契约引用，Phase 1 的完整 fixture 不解析尚未实现的假设集。
EventClock 的计算与结构留给 Phase 3，Phase 1 不伪造运行时钟。
枚举增加或语义改变需要显式 Schema 版本迁移；配置不改变内部状态枚举。

额外辅助契约仅服务上述领域：固定 VersionRef、带可用时间的 InputVersionRef、派生信封、PITQuery、PublicPIT、
观察窗、SampleStatistic、实体引用和 OfflineFixture。通用解析/JSON Schema 完全使用 Pydantic；不另建 Schema 框架。
`configs/schemas_v0.1.json` 是 11 个公共模型的 Pydantic 导出快照，测试确保与运行模型一致。
单个 JSON Schema 只能表达字段和局部形状；跨字段时间关系与跨对象引用必须再经过 Pydantic 及 OfflineFixture 校验。

## PIT 门槛与引用校验

| 字段 | 时间含义 |
|---|---|
| published_at | 来源声明发布时间，允许未知；不作为本系统可用门槛的替代 |
| public_available_at | 该内容版本可证明向公众公开的时间；不等于抓取/研究时间 |
| first_seen_at | 本系统首次看到该版本 |
| collected_at | 原始响应完整接收 |
| ready_at | 解析、规范化和必需校验完成；不等于事实确认 |
| recorded_at | 该版本成功耐久化提交完成；本Phase仅验证fixture声明 |
| available_at | 正式研究最早可用时间 |
| computed_at | 派生结果实际计算完成 |

所有时间拒绝 naive/数值时间戳，解析后统一 UTC；输入支持带时区 RFC3339，中文示例采用 +08:00。
原始 Evidence：`available_at >= max(first_seen_at, collected_at, ready_at, recorded_at)`。
派生对象：`available_at >= max(all_input_available_at, computed_at, recorded_at)`，且计算不能早于输入。
接收10:00:02、ready10:00:05、提交10:00:05，10:00:03不可见；提交延到10:00:07，10:00:06仍不可见。
缺少 ready/recorded 或校验失败不能形成正式可见 Evidence；历史有效日期不提前知识门槛。

`LIVE_FORWARD` 与 `OBSERVED_REPLAY` 使用真实 available_at；回放可读取已保存 LIVE 版本，回放产出不能冒充 LIVE。
`PUBLIC_PIT_RESEARCH` 保留真实时间，额外保存公开证明、模拟延迟、research_available_at 和派生 research_computed_at，
只按模拟模式查询，不能混入实盘/Forward。证明文本这里只检查存在，不声称已核实历史档案真实性。
统计使用结果最晚可知时间；公开模拟也必须以模拟计算截止时点限制统计及观察窗，不用较晚实际计算时间放行未来结果。

单对象校验验证声明的时间及引用形状；只有完整 OfflineFixture 才验证引用对象存在、类型正确、声明时间与实际版本一致、
输入当时可见、无重复/循环版本输入、原始文本与内容摘要一致。固定引用不自动选 latest。
`inspect` 返回截至当时所有合格版本；版本替代、合并分裂、Ledger 与历史视图选择由后续 Phase 实现。
`content_hash` 口径是模型规范化后的完整 JSON（排除自身 content_hash，含默认值，UTC，UTF-8，排序键，紧凑分隔符）；
`raw_content_hash` 对原始 UTF-8 字节计算。SHA-256 证明完整性，不证明事件事实。
fixture 生成辅助位于 tests/factories.py，仅用于可复现测试数据，不提供生产写入/自动补造时间。

## 未知、降级与边界

内部 fact/narrative/pricing/mapping/grade/impact_direction 未声明值严格拒绝，Phase 1 仅声明词表。
三个外部输入分类通过 `contracts.external.normalize_external` 显式映射：未识别字符串→OTHER+原样raw_type，
缺失→UNKNOWN+缺失原因；Pydantic 本身不静默纠正任意值。不增加可信度、不改变 claim_kind 或后续验证条件。
外部类型字段分别存在于 Statement、EvidenceVersion、EventVersion，原值不会互相覆盖。

未知占比/粉丝数/画像指标保留 null，并在画像记录 missing_reason；样本计数必须确实已知，不能拿0表示未查。
零样本统计率为 null；小样本分子/分母保留，不称为校准概率。followers 不自动改变 reliability_band。
HOLD/QUARANTINED 不可见；DEGRADED 可继续研究但必须携带 reason_codes。
授权 UNKNOWN 不等于允许无限抓取、永久保存或商用；Phase 1 只记录，不建立授权执行系统。
代码许可证不授予数据/API使用权。

本Phase未实现或未验证：真实 durable transaction、数据库Ledger、Origin去重、Novelty、状态机、网络采集、
LLM/TARGET/ALT/NULL/Red Team执行、产业/公司/证券映射、定价/排名、收益验证及自动交易。
原始时间和公开证明、用户文本事实真实性仍须真实数据验收；fixture PASS 不等于 Live PASS。
没有改动冻结总体文档、开源矩阵、Market Engine、其依赖或旧CI，也没有把账户范围引入事件研究。

## 依赖与许可证

运行直接依赖 Pydantic 2.12.5（MIT）；测试直接依赖 pytest 9.0.2（MIT），使用冻结矩阵的 DIRECT_DEPENDENCY 选择。
`requirements.lock` 锁全部运行/测试/构建传递版本与支持平台的发行 wheel SHA-256；
`DEPENDENCY_MANIFEST.json` 保存指定版本 PyPI 元数据定位及 wheel 摘要。未重新搜索或引入任何大型金融框架。

| 依赖 | 锁定版本 | 许可 |
|---|---|---|
| pydantic / pydantic_core | 2.12.5 / 2.41.5 | MIT |
| annotated-types / typing-inspection | 0.8.0 / 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| pytest / pluggy / iniconfig | 9.0.2 / 1.6.0 / 2.3.0 | MIT |
| colorama（Windows） | 0.4.6 | BSD-3-Clause |
| Pygments | 2.21.0 | BSD-2-Clause |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| setuptools（构建） | 80.9.0 | MIT；其内嵌发行组件许可见原文 |
| wheel（构建） | 0.45.1 | MIT；内嵌 packaging 为 Apache-2.0 OR BSD-2-Clause |

许可证原文及构建工具内嵌 NOTICE 保存在 THIRD_PARTY_NOTICES.md；以已安装指定版本发行文件为依据。
Python/安装器由环境提供；pip 不作为 X 运行/测试依赖。未为 X 仓库擅自指定开源许可证。
验证仅覆盖 X 使用的接口，不跑第三方项目全套测试；原始结果见 VALIDATION_REPORT.md 与本PR独立CI。
