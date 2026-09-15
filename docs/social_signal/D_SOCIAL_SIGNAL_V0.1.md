# D SOCIAL SIGNAL V0.1 — LOW-USAGE MINIMAL PILOT

EARLY DISCOVERY ONLY / NOT TRUTH VALIDATION.

基线 PR #28：`259c4788ccee4dacd827882779c8d9466256a674`。独立 stacked
分支 `codex/x-social-signal-v01`；不修改 Phase 1–10、L1、Market Engine 或 PR #28。

## 唯一范围

Bluesky public AppView searchPosts/getAuthorFeed、官方 Firebase HN
newstories/updates/item（仅 story）、单实例 Mastodon public timeline。
匿名 HTTP GET；复用 Phase 2 HTTPAdapter、RawObservation、Evidence、Origin、
Novelty、Event、Ledger、Cursor、SourceHealth、回执与 publication fence。
无新数据库实现、发行依赖、评分、事实确认、证券映射、LLM、市场数据或交易。

## 严格契约

SocialContent 保存平台、native_id、作者、创建时间、正文/标题/原链接/规范 URL、
语言及可空互动计数。未知字段不补零。SocialObservation 复用 DerivedEnvelope，
增加固定 source_ref/evidence_refs、raw_ref、response_locator、first_seen_at、
received_at、normalized_hash、lifecycle。content_hash 是账本标准对象摘要；
normalized_hash 是规范化内容摘要；原响应摘要在 Evidence.raw_content_hash。

`platform + native_id` 是唯一逻辑身份。Mastodon 的 native_id 加实例命名空间，
避免不同实例的本地数值 ID 冲突。相同规范化内容只返回 DUPLICATE，不追加社交
版本。正文或计数变化追加 UPDATED，A→B→A 是三个版本。NEW/UPDATED 等结果
由收集返回值给出；DUPLICATE 不伪造一个新持久化版本。

HN 明确 deleted=true 记 EXPLICIT_DELETED；API null 仅记
DELETED_OR_MISSING_UNKNOWN。时间线未出现某帖不推断删除。所有 Raw/Evidence
append-only，删除状态也保留旧原文。编辑/删除通过离线 fixture 验证。

默认 SOCIAL_LEAD；保留 COMMUNITY_DISCUSSION、TECH_SIGNAL、RUMOR、UNKNOWN
词表，但不运行分类模型。OFFICIAL_SOCIAL_STATEMENT 在本版本机器拒绝，直到未来
独立 AuthorIdentity 资格验收。普通社交永远不能输出 CONFIRMED_FACT。
全部输出 EVENT_INVESTIGATION_REQUIRED；后续事实确认必须经 A/B/C 正式来源。

跨平台只比较逐字相同 canonical_url/original_url，建立显式引用关联。
不得剥离查询参数、文本相似合并或声称独立确认。Origin 未知仍 HOLD；
Novelty 沿用 Phase 2 保守规则，不推断 R2–R5。

## 时间、持久化和恢复

created_at 是来源声称的创建时间；HTTP 首次接收和接收完成分别来自适配器时钟。
逻辑 SocialObservation 的 first_seen_at 保留首版时间；available_at 由现有提交
回执/fence 决定，不早于接收/计算/耐久化。不把历史帖子创建时间回填系统可知时间。
旧 as_of 使用 Ledger.history/replay，后续版本不得污染旧 cutoff。

原始响应先存 Phase 2，再发布 social，最后推进 Cursor。feed 响应的 Event
仅是 UNVERIFIED 传输信封，不能统计成额外独立事实；各帖子引用完整响应原文。
若后缀提交失败，成功 cursor 不前进，重试恢复已经提交的前缀。
Social schema 通过导入 xevent.social.pilot 注册到现有 Ledger MODELS；
重新打开含 SocialObservation 的数据库前同样需要该导入。

Bluesky 保存官方分页 cursor，resume 时继续页面；HN 保存最大已见 item id
（newstories/updates 仅发现 ID，不自动全量展开）；Mastodon 保存实例 since_id。
每个端点注册独立 Source；每次一个有界 HTTP 请求。resume=False 用于同一固定
端点的重复 smoke。HN ID discovery 和选定 item 是分别限定的请求，不抓评论树。
失败只更新本 SourceHealth；cursor 和最后成功时点保留。限流遵守现有
Retry-After HOLD；不得绕过登录/认证/跳转。Pilot attempts=1，禁止自动追加重试。

## 资格、运行与退出

source_qualifications.json 登记三个候选来源；QUALIFIED 必须有明确证据、允许
原文留存且无需认证。审核内容摘要绑定在已注册 Source.retention_policy，
请求前校验来源版本、端点、平台、审核时间和授权。公开 API 不等于自动获授权。
Mastodon 只审核 mastodon.social，不向其他实例扩展扫描。

本轮审核：Bluesky 条款页 403；HN 文档提供公共数据 API，但本次未确认原文
留存许可；mastodon.social 页面配置显示 public timeline disabled，且留存授权
未确认。三个来源均 HOLD_SOURCE_AUTHORIZATION，禁止内容 live smoke。
文档/条款查看不计为社交内容读取。真实 SocialObservation 数量全部 0。

Windows 本地运行：使用现有 Python 3.12，数据目录
`C:\Users\51650\XRealLanding\social-v01`，与 Git/L1 DB 分开。
`python scripts/social_signal/run_pilot.py --runtime <absolute-external-path>`
默认仅登记审核/来源并报告 HOLD；只有全部审核通过且显式 --live 才请求内容。
禁止把 raw、DB、日志、Cookie、token 或秘密提交 Git。沿用已存在 .gitignore。

OFFLINE_CI 与 LIVE_MANUAL_SMOKE 分离。CI socket fence 不变。
开发只跑新 focused；代码冻结后一次 final full/PIT；通过后提交最终 HEAD，
再一次四环境 exact-head CI。真实每源最多首次+重复两轮，不制造真实编辑/删除。

仅三个来源真实读取、去重/cursor/health/PIT/非事实 Gate 和原测试都通过后，才可
D_SOCIAL_SIGNAL_ENGINEERING_READY。否则 HOLD。D 不解除 L1 的
HOLD_REAL_EVENT_SOURCE_QUALIFICATION，也不解除 L2/L3/L4 或模型/行情/排名校准 HOLD。
API_BUDGET=0；无付费 API。不启动下一阶段。

## 本地最终验收（Python 3.12.10）

```text
focused: 44 passed in 15.13s
full: 912 passed in 2906.66s (0:48:26)
PIT: 292 passed, 620 deselected in 1447.78s (0:24:07)
```

最终 full/PIT 各执行一次。原 868 项保留，新增 44 项；其中新增 6 项 PIT。
真实三源 SocialObservation=0；默认本地运行验证三源 AUTHORIZATION_HOLD，
未请求社交内容 API。离线 duplicate/update、cursor、restart、PIT、SourceHealth
与非事实 Gate 通过，不能替代 live 资格。无新发行依赖或第三方代码许可证。
四环境 CI 将在最终 HEAD 发布后只触发一次，结果记录于 Draft PR 与 Issue #29，
避免为记录 CI 结果再次改动该 HEAD。当前正式状态 HOLD。
