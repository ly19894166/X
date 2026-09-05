# OPEN_SOURCE_REFERENCE_MATRIX_V0.1

X Event Engine 一次性开源复用审查；核验日期：2026-09-06。状态：**FROZEN_V0.1**。冻结的是模块选择、复用方式及排除理由；不是声称最新主干已完成安装、供应链或运行验收。本轮只读 GitHub 元数据、提交树、许可证及指定源文件/测试，没有安装、执行或复制第三方代码。

## 1. 决策规则

- `DIRECT_DEPENDENCY`：复用公共 API 的小型组件；不重写它的通用能力。首次引入选兼容稳定发布版、锁版本/哈希和传递依赖，记录许可证/NOTICE；不直接追随本次审查的开发主干。
- `REFERENCE_IMPLEMENTATION`：阅读特定实现和测试，按 X 契约实现领域适配；本轮不复制。将来若复制允许许可的少量代码，保留来源/版权/NOTICE和修改说明，并检验该文件/依赖的实际许可证。
- `ARCHITECTURE_ONLY`：只借职责划分、数据流和失败处理思想，不引入包、不复制代码。
- `X_NATIVE`：X 自主定义领域语义与验收；底层仍复用 Schema、数据库、网络库。自主领域设计不等于从头实现数据库、调度框架或 JSON 校验器。

X 当前仓库未见 LICENSE，不能擅自替 X 选择开源授权。MIT、BSD、Apache 等候选依赖按各自声明履约；根许可证不自动覆盖第三方文件、模型权重、数据集或付费数据API。AGPL/强 copyleft 或许可不明的候选默认 ARCHITECTURE_ONLY，禁止代码复制；不假设独立进程/HTTP接入即可免除许可证义务。具体许可证冲突只阻塞该组件，不停止其他Phase。

## 2. 三个指定框架的当前证据与选择

| 项目 | 冻结提交、维护快照 | 实际核读 | 结论 |
|---|---|---|---|
| TauricResearch/TradingAgents | [9dee508c4466](https://github.com/TauricResearch/TradingAgents/tree/9dee508c44662702281a8dbaad1f7b42179b5ba7)；Apache-2.0；未归档；最近推送 2026-09-01T05:38:45Z | [LICENSE](https://github.com/TauricResearch/TradingAgents/blob/9dee508c44662702281a8dbaad1f7b42179b5ba7/LICENSE)；[pyproject.toml](https://github.com/TauricResearch/TradingAgents/blob/9dee508c44662702281a8dbaad1f7b42179b5ba7/pyproject.toml)；[tradingagents/agents/analysts/sentiment_analyst.py](https://github.com/TauricResearch/TradingAgents/blob/9dee508c44662702281a8dbaad1f7b42179b5ba7/tradingagents/agents/analysts/sentiment_analyst.py)；[tests/test_news_lookahead.py](https://github.com/TauricResearch/TradingAgents/blob/9dee508c44662702281a8dbaad1f7b42179b5ba7/tests/test_news_lookahead.py)；[tests/test_memory_pointintime.py](https://github.com/TauricResearch/TradingAgents/blob/9dee508c44662702281a8dbaad1f7b42179b5ba7/tests/test_memory_pointintime.py) | 局部 REFERENCE_IMPLEMENTATION；整体 ARCHITECTURE_ONLY。结构化证据先注入、历史新闻窗口及已结算记忆的PIT回归值得参考；不引入整套 LangChain/LangGraph/Backtrader 或 BUY/SELL/投票流程。 |
| AI4Finance-Foundation/FinGPT | [1aac55586aa6](https://github.com/AI4Finance-Foundation/FinGPT/tree/1aac55586aa6ce12da602b69eeb739459f54a826)；MIT；未归档；最近推送 2026-09-03T06:02:34Z | [LICENSE](https://github.com/AI4Finance-Foundation/FinGPT/blob/1aac55586aa6ce12da602b69eeb739459f54a826/LICENSE)；[fingpt/FinGPT_Benchmark/readme.md](https://github.com/AI4Finance-Foundation/FinGPT/blob/1aac55586aa6ce12da602b69eeb739459f54a826/fingpt/FinGPT_Benchmark/readme.md)；[fingpt/FinGPT_Benchmark/benchmarks/ner.py](https://github.com/AI4Finance-Foundation/FinGPT/blob/1aac55586aa6ce12da602b69eeb739459f54a826/fingpt/FinGPT_Benchmark/benchmarks/ner.py)；[fingpt/FinGPT_Benchmark/benchmarks/finred.py](https://github.com/AI4Finance-Foundation/FinGPT/blob/1aac55586aa6ce12da602b69eeb739459f54a826/fingpt/FinGPT_Benchmark/benchmarks/finred.py)；[fingpt/FinGPT_Forecaster/requirements.txt](https://github.com/AI4Finance-Foundation/FinGPT/blob/1aac55586aa6ce12da602b69eeb739459f54a826/fingpt/FinGPT_Forecaster/requirements.txt) | NER/关系抽取评估格式 REFERENCE_IMPLEMENTATION；训练/预测框架 ARCHITECTURE_ONLY。基准含实体/关系抽取，但不能当作A股公司身份、业务暴露或因果证据；不下载模型/数据集、不训练GPU模型。 |
| AI4Finance-Foundation/FinRobot | [d221910096de](https://github.com/AI4Finance-Foundation/FinRobot/tree/d221910096de87579b02f8f0674652bf1a175f51)；Apache-2.0；未归档；最近推送 2026-08-23T12:06:08Z | [LICENSE](https://github.com/AI4Finance-Foundation/FinRobot/blob/d221910096de87579b02f8f0674652bf1a175f51/LICENSE)；[requirements.txt](https://github.com/AI4Finance-Foundation/FinRobot/blob/d221910096de87579b02f8f0674652bf1a175f51/requirements.txt)；[finrobot/agents/workflow.py](https://github.com/AI4Finance-Foundation/FinRobot/blob/d221910096de87579b02f8f0674652bf1a175f51/finrobot/agents/workflow.py)；[finrobot/data_source/filings_src/sec_filings.py](https://github.com/AI4Finance-Foundation/FinRobot/blob/d221910096de87579b02f8f0674652bf1a175f51/finrobot/data_source/filings_src/sec_filings.py)；[finrobot_equity/core/tests/test_modules.py](https://github.com/AI4Finance-Foundation/FinRobot/blob/d221910096de87579b02f8f0674652bf1a175f51/finrobot_equity/core/tests/test_modules.py) | ARCHITECTURE_ONLY。参考工具/数据层/分析职责分离；AutoGen会话编排和SEC提取不适合作为X整体依赖，不能默认已覆盖X所需available_at/PIT。 |

实际观察和限制：

1. TradingAgents sentiment 源码明确描述旧提示词要求并不存在的社媒数据导致捏造，当前选择预取再结构化注入。X继承证据先行，但不能接受“没有结构化结果就自由文本当合格输出”的宽松后备。
2. `test_news_lookahead.py` 覆盖无时间、未来新闻、UTC和上界；其中 live 可保留无日期文章的行为不能直接作为 X 历史可知证明。X 当前可记录实际 first_seen，但回放不提前公开时间。`test_memory_pointintime.py` 过滤晚于研究日才结算的经验；X需要精确到时间戳及每版本，不仅日期。
3. FinGPT NER使用实体类型/序列评估，FinRED使用白名单关系和文本引用验证。任务基准存在不等于持续集成或金融Alpha已验证；固定旧版 torch/transformers/PEFT 依赖表不适合整套并入。
4. FinRobot workflow 有 AutoGen 多角色和工具注册；requirements 包含许多财务、文档、可视化依赖及版本固定，容易扩大安装/维护范围。核读的模块测试主要检查导入与方法/示例，不能证明端到端PIT正确；SEC提取代码的日期默认值和 SIGALRM 也不能直接复用于 Windows 的时间契约。
5. 三项目“最近有推送”只证明活动快照，不证明关键模块刚维护、性能领先、所有测试通过或安全。没有核实原讨论中的 star 数、推荐评分或盈利说法，本矩阵不沿用这些数字。

## 3. 小型基础设施复用清单

| X模块 / Phase | 分类 | 选定组件 | 许可证与提交证据 | 测试与边界 |
| 严格类型、枚举、JSON Schema；禁止自写通用校验器 / P1 | DIRECT_DEPENDENCY | Pydantic | [MIT](https://github.com/pydantic/pydantic/blob/c23cb86ef197693fc016437614f174252a3d189a/LICENSE)；[c23cb86ef197](https://github.com/pydantic/pydantic/tree/c23cb86ef197693fc016437614f174252a3d189a) | 上游[测试目录](https://github.com/pydantic/pydantic/tree/c23cb86ef197693fc016437614f174252a3d189a/tests)已确认；本轮未跑上游测试。首次引入测X实际使用接口及失败路径。 |
| SQL访问、事务和SQLite/PostgreSQL适配；Ledger语义仍X定义 / P2 | DIRECT_DEPENDENCY | SQLAlchemy | [MIT](https://github.com/sqlalchemy/sqlalchemy/blob/de83fa72d787136785624fd8981e1d71e9f427ab/LICENSE)；[de83fa72d787](https://github.com/sqlalchemy/sqlalchemy/tree/de83fa72d787136785624fd8981e1d71e9f427ab) | 上游[测试目录](https://github.com/sqlalchemy/sqlalchemy/tree/de83fa72d787136785624fd8981e1d71e9f427ab/test)已确认；本轮未跑上游测试。首次引入测X实际使用接口及失败路径。 |
| 连接池、超时、请求/响应；不自行写HTTP客户端 / P2采集适配 | DIRECT_DEPENDENCY | HTTPX | [BSD-3-Clause](https://github.com/encode/httpx/blob/b5addb64f0161ff6bfe94c124ef76f6a1fba5254/LICENSE.md)；[b5addb64f016](https://github.com/encode/httpx/tree/b5addb64f0161ff6bfe94c124ef76f6a1fba5254) | 上游[测试目录](https://github.com/encode/httpx/tree/b5addb64f0161ff6bfe94c124ef76f6a1fba5254/tests)已确认；本轮未跑上游测试。首次引入测X实际使用接口及失败路径。 |
| 有上限的重试/退避；X决定可重试错误与幂等边界 / P2采集/任务调用 | DIRECT_DEPENDENCY | Tenacity | [Apache-2.0](https://github.com/jd/tenacity/blob/3e58094d3bc414975aad9eadf343a32bdb3b89b3/LICENSE)；[3e58094d3bc4](https://github.com/jd/tenacity/tree/3e58094d3bc414975aad9eadf343a32bdb3b89b3) | 上游[测试目录](https://github.com/jd/tenacity/tree/3e58094d3bc414975aad9eadf343a32bdb3b89b3/tests)已确认；本轮未跑上游测试。首次引入测X实际使用接口及失败路径。 |
| 成熟RSS/Atom解析；HTTP获取交HTTPX，证据时间由X校验 / P2 RSS入口 | DIRECT_DEPENDENCY | feedparser | [代码及测试为BSD-2-Clause文本；GitHub元数据NOASSERTION](https://github.com/kurtmckee/feedparser/blob/a22c5521cbb109871f1a2318948581901bd47e26/LICENSE)；[a22c5521cbb1](https://github.com/kurtmckee/feedparser/tree/a22c5521cbb109871f1a2318948581901bd47e26) | 上游[测试目录](https://github.com/kurtmckee/feedparser/tree/a22c5521cbb109871f1a2318948581901bd47e26/tests)已确认；本轮未跑上游测试。首次引入测X实际使用接口及失败路径。 |
| 测试运行、fixture、参数化；不造测试框架 / P1起 | DIRECT_DEPENDENCY | pytest | [MIT](https://github.com/pytest-dev/pytest/blob/51e9a9f148cd2509a31e3fa0d2b1b3204c2b0dd7/LICENSE)；[51e9a9f148cd](https://github.com/pytest-dev/pytest/tree/51e9a9f148cd2509a31e3fa0d2b1b3204c2b0dd7) | 上游[测试目录](https://github.com/pytest-dev/pytest/tree/51e9a9f148cd2509a31e3fa0d2b1b3204c2b0dd7/testing)已确认；本轮未跑上游测试。首次引入测X实际使用接口及失败路径。 |

feedparser 不能只凭 GitHub 的 NOASSERTION 元数据断言无许可；本轮已读取 LICENSE 正文，代码/测试为两条款BSD式许可，文档另列类似许可，不复制其文档。本清单组件均核读根目录/测试目录存在及许可证，不声称完整审计测试覆盖率或发布版供应链。

Python 标准库的 datetime/zoneinfo/hashlib/json/logging/pathlib、SQLite 事务持久化优先使用，不另造时间/哈希/序列化/文件系统。初版单进程有界任务循环使用标准库；仅明确遇到调度持久化/多机并发阻塞再评估现成调度组件，禁止为了形式上的“复用”先引入重量调度框架。Parquet/DuckDB/PostgreSQL驱动在真实数据量要求时再做局部依赖锁定，非本轮新增安装。

## 4. 每个领域模块的复用边界

| X模块 | 主分类 | 可复用部分 / 自主部分 |
|---|---|---|
| Source / Actor注册 | X_NATIVE | Pydantic/SQLAlchemy DIRECT_DEPENDENCY；五级来源、人物×主题及时间语义自主 |
| Collector网络/RSS/重试 | DIRECT_DEPENDENCY | HTTPX + feedparser + Tenacity；source adapter只写供应商字段映射和时间/单位规则 |
| Evidence原始档案/引用 | X_NATIVE | 标准库哈希、SQL事务；原始/首次/编辑/删除、PIT与引用定位自主 |
| Event DNA / Event Ledger / Origin / Novelty | X_NATIVE | 通用数据库存储复用；身份、R0—R5、幂等业务键与演进规则自主 |
| 事实/叙事/价格三状态机 | X_NATIVE | 不照搬TradingAgents的交易决策状态；不写通用状态机库 |
| Reality / Narrative 双世界 | X_NATIVE | 原生双路径和事实/传播证据隔离 |
| 金融NER / 关系抽取评估 | REFERENCE_IMPLEMENTATION | 参考FinGPT指定文件的输入/输出与评价；不拿其模型输出当业务事实 |
| Impact Variable / X产业本体 | X_NATIVE | 有界枚举、产业树、外部分行业crosswalk自主 |
| Company Exposure Master | X_NATIVE | 公司事实、证券身份、地理/产品/客户、有效期与可知期自主 |
| Transmission Graph | X_NATIVE | SQL表+有限遍历即可；真实/叙事及正负路径、边证据自主 |
| 证据预注入/结构化模型适配 | REFERENCE_IMPLEMENTATION | 参考TradingAgents sentiment数据包设计；X Schema与工具权限自行控制 |
| TARGET / ALT / NULL 与Red Team | X_NATIVE | FinRobot/TradingAgents仅ARCHITECTURE_ONLY角色启发；假设和裁判准则由X定义 |
| Price-in / Remaining Edge | X_NATIVE | 确定性计算可用既有NumPy/Pandas接口，不能移植通用交易评分 |
| α1/α2/β研究排名 | X_NATIVE | 独立原始维度、合理风险规则，账户不参与Alpha |
| Shadow / Forward / PIT评估 | X_NATIVE | pytest复用；TradingAgents PIT回归为REFERENCE_IMPLEMENTATION，X有available_at及全样本分母要求 |
| CLI / 日志 / 服务入口 | DIRECT_DEPENDENCY | 初版argparse/logging/标准进程入口；界面中文，不先引入Dashboard框架 |
| Market Engine只读桥 | X_NATIVE | 使用版本化导出协议；不复制未合并xalpha包或改写其目标 |
| TradingAgents/FinRobot整套编排 | ARCHITECTURE_ONLY | 不直接依赖整个框架，不导入交易/代码执行工具 |
| AGPL/许可不明的可选项目 | ARCHITECTURE_ONLY | 不复制代码；本轮无需扩展全网搜索，不指定其为运行依赖 |

## 5. 冻结与最小复审流程

本轮选定的小型组件足以支持Phase1—9的通用基础，无明确阻塞，不扩展“更好框架”全网搜寻。未来任务必须先读取此文件，禁止每Phase重新调查TradingAgents/FinGPT/FinRobot。

只有明确证据表明选定方案不能满足目标时局部复审：例如支持的Python/Windows不兼容、维护/安全问题、许可证冲突、实测无法满足任务规模或缺必要能力。创建 `OSS_REVIEW_DELTA`：阻塞复现、受影响模块、最多少量替代项、许可/成本/迁移比较、决定和新版本；不重开全系统研究。首次选择稳定包版本、核验传递许可证和运行focused tests属于引入验收，不是重新全网开源研究。

经济研究逻辑的原生性是为了保留X的定义与可审计性；它不要求自己写HTTP、数据库、RSS、类型校验、重试框架。本轮未增加依赖、未复制第三方源文件，Phase0文档冻结之后才按Issue逐步实施。

