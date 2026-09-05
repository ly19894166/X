# Phase 1 离线验收记录

日期：2026-09-06。输入文档基线：`0a5469a0b90c9302ebb3889e1088486404bd87bb`。
恢复时分支 `build/x-event-engine-phase1` 已存在，未提交的 common.py / models.py / 包配置及虚拟环境被保留并继续完成。
没有重新调查开源项目、改写总体架构或启动 Phase 2。

## 本地原始结果

环境：Windows x64，CPython 3.11.9，独立 `.venv`；没有导入 Market Engine 或使用其环境。
最终代码校验命令在 `subsystems/event_engine/` 执行。

```text
python -m pytest -q
........................................................................ [ 75%]
.......................                                                  [100%]
95 passed in 0.69s

python -m pytest -q -m pit
.........................................                                [100%]
41 passed, 54 deselected in 0.22s

python -m pip check
No broken requirements found.

x-event ingest --fixture configs/offline_fixture.zh-CN.json
校验通过：9 个版本；离线校验，未持久化。
```

PIT 专项 41 项是 95 项总测试的子集，不相加为136项。
依赖锁执行 `pip install --dry-run --ignore-installed --require-hashes --only-binary=:all: -r requirements.lock` 成功；
完整解析13个指定版本，没有缺失传递依赖，验证本平台发行 wheel 哈希。
可编辑独立安装 `pip install --no-build-isolation --no-deps -e .` 成功，安装后的 `x-event` 入口运行成功。

## 覆盖与拒绝条件

| 验收内容 | 结果与证据 |
|---|---|
| 11个公共Schema / JSON Schema冻结 / round-trip | test_contracts.py；运行模型与 configs/schemas_v0.1.json 相等 |
| 主题画像、数值未知、小样本、许可证/授权区分 | 画像null不补0、粉丝数不升事实可信度、来源授权未知不默认开启 |
| 六位代码保留前导零、非法枚举、额外字段、固定版本 | 拒绝数字代码、动态latest、未知内部状态、账户成本额外字段 |
| 外部分类与发言种类 | 新场景→OTHER/raw_type，保留Evidence与原claim；支持六类主张 |
| 接收10:00:02、ready/提交10:00:05 | 10:00:03不可见，10:00:05可见 |
| ready10:00:05、提交10:00:07 | 10:00:06不可见，10:00:07可见 |
| 缺关键时间/校验失败/提交门槛 | FAIL_CLOSED；QUARANTINED不可见，不能发布READY |
| 来源/证据/事件引用完整性 | 拒绝缺失、错类型、虚假输入时间、重复版本、循环输入、输入HOLD或混入回放 |
| 画像与人物职位PIT | 未来结果、未来观察窗、后来职位不得回填；公开模拟使用模拟截止时间 |
| 原始字节与版本摘要 | 改写原文/标题会拒绝；哈希不代表真实性 |
| CLI | 中文成功/失败，截止点HOLD再可见，JSON Schema导出，无daemon命令 |

## CI 与尚未验证

新增 `.github/workflows/event-engine-ci.yml`，仅在本子系统/自身工作流的 PR 改动触发，
矩阵 Windows/Linux × Python3.11/3.12，复用同一组focused/PIT测试并校验CLI。
远端实际结果在 PR Checks 留存，不能用本地Windows结果代替尚未完成的其他环境CI。

HOLD范围：真实原始来源公开时间证明、采集就绪时间、数据库提交耐久性、真实账户或数据授权、
持续在线覆盖与Alpha表现。Phase1只验证fixture声明，不声称真实持久化或Live验收通过。
单对象Schema检查不替代完整引用校验；真实跨记录事务、Ledger、版本合并/分裂/去重、状态转换均未实现。
根文档仍保留Phase0历史状态描述；当前阶段以Issue #6及本PR为准，未擅自修改冻结文档。
PR采用文档分支为基线，因为PR #3尚未合并；该PR只增加Phase1文件，不更改PR #3内容。
人工复审与合并留给用户；本轮不自动启动后续Phase。
