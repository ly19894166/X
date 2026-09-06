# Phase 2：持久化事件底座

输入基线：Phase 1人工通过提交 `8134527e0270143ef9827effa776f7b90f372642`，Issue #7。
本增量只建设SQLite、原始档案、版本历史、Origin、确定性Novelty、Cursor、Outbox、SourceHealth和最小HTTP/RSS入口。
原95项契约测试保留，不引入事件三状态机转换、EventClock、LLM、产业/股票/定价或交易功能。

## 安装和最小使用

独立目录 `subsystems/event_engine/`，CPython3.11/3.12，Windows/Linux x64。
先安装锁定构建工具，再安装全部依赖；feedparser的sgmllib3k只有上游sdist，使用锁定源码包SHA-256和已锁构建工具，不在线寻找替代框架。

```text
python -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
python -m pip install --require-hashes --no-build-isolation --only-binary=:all: --no-binary=sgmllib3k -r requirements.lock
python -m pip install --no-build-isolation --no-deps -e .
x-event ledger-ingest --db event.sqlite --fixture configs/phase2_observations.zh-CN.json
x-event ledger-replay --db event.sqlite --as-of 2099-01-01T00:00:00Z
x-event ledger-recover --db event.sqlite
```

fixture为虚构“原文→编辑→删除”。接收时间是fixture声明，提交/可用时间由运行时记录，不能把该fixture当真实历史采集。
原Phase1 `ingest --fixture` 仍只做离线校验。`ledger-replay` 不推进恢复或游标，不创建不存在的数据库。
写入/显式恢复时才对已提交但缺回执的批次保守恢复；SQLAlchemy异常/Schema异常为FAIL_CLOSED。
目录不启动daemon、调度器或任何真实网络请求。

## 数据库和事务

[Migration 1](migrations/README.md) 使用SQLAlchemy Core；SQLite WAL、foreign_keys ON、synchronous FULL、BEGIN IMMEDIATE、唯一幂等键。
业务数据和原始BLOB全部位于同一SQLite事务，不存在文件archive与DB双写。UPDATE/DELETE被数据库触发器拒绝。
RawObservation包含原始响应、稳定来源/定位/内容版本、first_seen、collected、可选published、原始/规范化hash及明确变更类型。
原始hash按字节，规范化hash仅折叠文本空白用于审计，不单凭规范化相似度强制合源。

业务事务同时写入：raw → EvidenceVersion/EvidenceChange → OriginClusterVersion/NoveltyDecision → EventVersion/EventLedgerEntry → OutboxJob。
事务中对象为待确认描述，不伪填正式recorded_at。COMMIT成功返回后记录完成时间上界，再验证领域描述、原始摘要及输入。
不可变commit_receipts表保存这一提交后的时间测量；它是发布目录，业务payload不被第二次覆盖。
`recorded_at`明确指业务数据原子事务成功提交后的观测上界，不是INSERT、COMMIT请求或回执目录写入开始。
`computed_at`为提交后确定性契约物化/校验完成时间的观测上界；与available_at一同冻结，所有输入可用时间必须不晚于此。
回执目录COMMIT也成功返回后，才采样研究可用时间；publication_fences追加保存这个完成后测量。
发布fence自身是控制记录，缺失时保持不可见；不拿回执写入前的时间冒充回执已完成。
专门测试回执提交延迟7秒时旧as_of仍看不到Evidence。

没有完整回执/fence的已提交批次为COMMITTED_UNATTESTED，查询与Outbox不会发布。恢复无法知道丢失的原始完成时刻时，
保守把恢复后的验证时点作为recorded_at/available_at上界，绝不回填到早先接收时间。已存在回执不改写。
回执目录、发布fence分别追加控制事务；不宣称SQLite能在单个事务里预知自己的精确结束时间，也不把事务中的临时描述当正式研究版本。
正式PIT信封由不可变描述+提交后回执物化；不是将客户端自填recorded_at直接存成真值。

测试注入raw后、Evidence后、Ledger后、Outbox前、commit前、业务commit后、回执commit前/后故障；
另用独立子进程os._exit模拟未清理连接的真实退出和WAL恢复。所有情况下只能完整发布或保持未发布。
SQLite/操作系统/磁盘的fsync保证是依赖前提；没有证明硬件断电保护、网络文件系统或多主写入可用。
V0.1仅支持一个业务写入者。内存中只缓存已验证的不可变模型；每次读取仍核对描述、输入版本及原始摘要。

## 幂等、历史和Outbox

业务键由稳定source_id+locator+content_version构成；同键相同语义输入复用旧Evidence/Event，同键不同内容FAIL_CLOSED。
重试不改变原first_seen/collected；精确重复最多追加一个R0审计决定，不再新增逻辑事件或Outbox。
HTTP接收版本由最后已保存内容推进，A→B→A是三版；重启时依据已保存Evidence而非单靠Cursor判断。
编辑、删除和撤回只追加EvidenceChange及新EvidenceVersion，删除的空响应不能物理抹掉V1原文。

Outbox PENDING与业务Ledger同事务；DONE与消费结果在后续事务内追加，以稳定effect_key幂等。
当前只演示数据库内消费确认，不承诺外部副作用exactly-once；未来外部消费者必须使用effect_key幂等。
后续消费以自己的真实提交/可用时间引用原Outbox版本，不倒写原始任务或提前执行时间。
Replay按as_of筛选全部具体版本，保留HOLD/失败记录供审计；需要正式研究时仍使用Phase1可见性门槛。
不实现Phase3的合并/分裂/复活状态机或动态latest选择。

## Origin与Novelty规则

同事件作用域内精确原始字节hash、明确原始Evidence版本引用/转载链可以归到一个Origin。
已验证来源的一手内容可形成已知Origin；单凭文本相似或未知来源不能被算成独立共识。
不同事件即使同样的通用文本也不跨事件以hash强制合源。未知关系保留不同簇，independent_source_count为null/HOLD。
origin_count（当前不同簇数）和独立来源数量分开，不能把两者混为一谈。
independent_source_count按已验证一手来源身份单元保守计数：使用Evidence引用的固定Source版本，
要求该版本identity_status=VERIFIED、一手Evidence已校验且来源/证据未隔离。同一source_id的多个Origin只贡献一个单元；
已确认同源的多个来源也只贡献一个单元，跨簇共享来源身份继续去重。任一簇缺少可验证一手根则整体返回null/HOLD。
不同source_id代表登记时已核验的不同来源身份；本Phase不自动核验媒体控制关系或来源登记真实性。
后来Source身份升级不能替换旧Evidence引用的Source版本，也不能回填旧as_of独立来源数。

后来人工确认同源必须调用显式确认接口：保存覆盖原始簇的具体证据版本、新确认材料及原文片段；
片段须能在原始确认材料逐字定位，包含相关source_id和原始定位。此接口代表有记录的人工核验，
不声称字面引用本身能自动证明真实性。新OriginClusterVersion只影响之后as_of；旧时点计数保持原结果。

| 分类 | 确定性规则 |
|---|---|
| R0 | 稳定内容版本重复且语义指纹一致 |
| R1 | 新定位/转载证据，已有强Origin关系，且不是同定位编辑 |
| R2 | 完整来源结构JSON仅detail变化，字段集合一致 |
| R3 | 完整来源结构JSON的amount/effective_date变化 |
| R4 | 完整来源结构JSON的legal_status变化 |
| R5 | 一手来源完整结构JSON新增retracted=`"true"` |
| UNDETERMINED/HOLD | 普通文本更新、仅删除、字段无法核验，或不能按以上规则可靠区分 |

结构字段必须与原始JSON对象完整相等，不能截取“detail变化”而忽略正文重大变化。
普通HTTP/RSS Adapter不自动标这些结构字段；没有用LLM判断“重大”。
R2/R3/R4/R5是有来源定位的规则分类，不等于事件事实已确认。EventVersion三状态默认保持未验证/未知，不执行升级。
初始Event以本次ready_at设置last_material_update_at；后续仅R3/R4/R5推进该字段。
R1/R2/UNDETERMINED保留上一EventVersion的值；R0不产生新EventVersion。旧as_of的事件版本不变，不实现EventClock。
每个NoveltyDecision冻结reason_codes、具体输入/evidence refs、computed_at/recorded_at/available_at及policy_version。
HOLD不丢原始证据、不阻止后续研究；后来的决定不能改变旧时点已有决定。
未分类原始观察默认claim_kind=NARRATIVE保守留存，明确的类型由调用者声明，不默认把外部文本升级为FACT。

## 授权Gate、HTTP/RSS与Cursor

每次真实请求前重新验证：来源具体版本可见、enabled、terms_status=REVIEWED、
authorization_status=AUTHORIZED/NOT_REQUIRED、allowed_uses包含EVENT_RESEARCH、raw_retention_allowed=true。
DENIED/UNKNOWN默认不得请求；配置的访问限制无法由最小Adapter解释时HOLD。
运行时采集配置必须与已登记Source版本完全一致，不能用内存临时改授权绕过注册版本。
这是最小硬Gate，不是完整条款解释/授权系统，也不把公开可访问视为无限使用许可。

HTTPX明确User-Agent、connect5秒/其余10秒超时、1MiB响应上限，不跟随重定向。
Tenacity最多3次，仅网络/超时和429/500/502/503/504临时错误重试；默认每次等待上限5秒。
Retry-After秒数/HTTP日期均尊重；超过本轮上限则HOLD，不截短后提前请求。永久4xx/跳转不循环。
feedparser只接收已下载bytes，绝不传URL让其自行联网。输出解析的条目ID/标题/链接/原始发布时间文本，
同时原样保存HTTP/RSS完整响应。不会跟随条目链接，不自动将RSS每个条目生成股票/产业或独立研究事件。
响应到Event的种子/DNA关联由明确调用输入提供；自动事件语义发现留给后续Phase。
RSS响应级快照与条目级事件不是同一个概念，当前CLI示例明确采用响应观察种子。

collect_once先持久化响应，再追加Cursor/SourceHealth；响应已提交而Cursor失败时，下次重试复用既有版本。
Cursor保存位置、etag/last_modified/since_id及last_success/attempt/received；失败保留上次成功位置。
Cursor只表示采集进度，不冒充历史发布时间。推进成功位置必须引用已提交的本来源Evidence；304必须有既有成功位置，不能用空响应跳过未保存内容。
一个来源失败返回SOURCE_UNAVAILABLE，仅记录该来源健康降级。
CI网络连接被禁止；HTTP均MockTransport。没有手动Live smoke，没有任何已审核真实来源配置。
目前Live/历史公开时间语义/24小时覆盖均HOLD，成功下载只可称CURRENT_OBSERVATION_ONLY。

## 依赖和许可增量

直接新增：SQLAlchemy2.0.43（MIT）、HTTPX0.28.1（BSD-3-Clause）、Tenacity9.1.2（Apache-2.0）、feedparser6.0.12（BSD-2-Clause）。
新增传递：greenlet3.5.5（MIT AND PSF-2.0）、anyio4.15.1（MIT）、httpcore1.0.9（BSD-3-Clause）、
h11 0.16.0（MIT）、idna3.19（BSD-3-Clause）、certifi2026.7.22（MPL-2.0）、sgmllib3k1.0.0（上游声明BSD License）。
原有Pydantic/pytest及传递依赖版本保持。24个发行依赖版本/哈希锁在requirements.lock；构建工具另有bootstrap锁。
certifi只作为未修改的证书包依赖使用，保留其MPL许可，不复制修改证书包；不把其许可等同于X整体许可证。

**HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION**：sgmllib3k指定sdist与已安装元数据均声明BSD License，但未携带独立许可证全文或明确条款数。
已保留该发行版PKG-INFO、来源和SHA-256，未捏造缺失的许可文本；外部分发/打包前需补齐许可原文核验。
这是引入feedparser传递依赖时发现的具体缺口，不是重新开展开源研究；本轮不搜索替代框架或更改冻结矩阵。
许可证清单与数据/API使用授权分别记录。新增依赖的实际原文见THIRD_PARTY_NOTICES.md，哈希/发行定位见DEPENDENCY_MANIFEST.json。

## 停止点

PR以build/x-event-engine-phase1为base，仅Phase2增量。Issue #7保持OPEN待人工复审。
不合并或修改PR #3/#17，不动Market Engine PR #2、Issue #1、src/xalpha/或市场CI/标签/模型，不进入Phase3。
