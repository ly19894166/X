# Phase 7 验证记录

日期：2026-09-08。基线：`f58b8f869af99c9196480f7be5c5aa50970ff0b5`。
head分支：`build/x-event-engine-phase7`；stacked base：`build/x-event-engine-phase6`。
工程结果与真实模型/数据/Alpha验收分开；本文件不声明已完成Live。

## 最终源码本地原始结果

Windows Python 3.11.9，复用Phase2既有锁定环境，PYTHONPATH指向Phase7 src。没有安装/升级依赖。
按 focused → full → PIT 顺序执行：

```text
python -m pytest -q tests/test_phase7_research.py tests/test_phase7_pit.py
70 passed in 226.32s (0:03:46)

python -m pytest -q
551 passed in 492.97s (0:08:12)

python -m pytest -q -m pit
170 passed, 381 deselected in 214.32s (0:03:34)
```

原481项测试文件无修改；新增70项，其中17项PIT。以上是补齐Historical/Forward可见性Gate后的最终源码结果，不复用开发中间结果。

## 覆盖

- 正向TARGET、同事件机制ALT胜出、负向机制的替代解释、证据不足NULL、TARGET/ALT同时被反证、综合公司正负抵消。
- 独立Primary/RedTeam上下文、反方推翻、无分歧不裁定、有重大分歧最多一次裁定、失效TARGET不被无新事实复活。
- Graph HOLD、选择遗漏、未知/叙事路径不可升级；杜撰Evidence/Path/反方引用拒收；ALT不跨事件。
- Metric数值/口径/单位/币种/原始双span校验；无源数字、隐含数字、私有推理/额外字段、越权指令拒收。
- 外部注入仅作为数据；用户持仓/成本/喜好/后验收益/执行权限不能进入Packet，重复研究不受这些外部字段影响。
- 一次结构修复、请求/输出预算、未知单价HOLD、超时/Provider失败隔离、缓存命中及新输入失效、旧合法研究保留。
- 调用前预留与中断恢复不盲目重发；Packet事务rollback；JSON Schema/round-trip和replay确定性。
- 14:50开始14:52完成，14:51无模型结论；更正只影响新Packet；当前上游过期不调用模型；运行期间上游变化阻止新TARGET。
- Historical Packet/ModelResult/AnalysisRun不能通过LIVE_FORWARD可见性；历史输出仍使用实际发布时点，cache按模式隔离。
- 七十同源转载仍为一个Origin，不产生数量置信度加权；后来的CONTRADICTED触发HOLD，旧run不回填。

## CLI与中文fixture

通过既有CLI main等价调用成功导出HypothesisSet JSON Schema；正式命令为 `x-event schema --model HypothesisSet`。
`python -m xevent.research.fixture --db <新隔离库>` 成功，最终源码输出：

```text
声明：仅工程Mock结构化研究，不代表真实模型研究有效或投资建议
研究状态：MOCK_PASS
研究模式：MOCK_FORWARD
最终假设类型：NULL
```

所有测试继承原禁止真实socket的fixture。Windows asyncio自管道与该禁令冲突时改用标准库有界worker，未放宽网络隔离测试。

## CI与交付证据

原Event Engine Ubuntu/Windows × Python3.11/3.12四组继续运行full、PIT及全部既有演示，新增Phase7中文Mock演示。
对应新HEAD的实际run/job及原始结果在本Phase Draft PR / Issue #12验收记录核对。只有四组全部SUCCESS才标记
`PHASE7_ENGINEERING_COMPLETE_WAITING_REVIEW`；本地通过不替代远端CI。

## HOLD与边界

无新依赖、许可证或SQL迁移；仅Ledger/CLI类型注册最小接入，Phase1–6业务实现不改。Market Engine、src/xalpha、PR #2、Issue #1和Market CI不改。

持续HOLD：HOLD_MODEL_PROVIDER_LIVE、HOLD_MODEL_USAGE_COST_UNVERIFIED、HOLD_HISTORICAL_UNIVERSE_COVERAGE、HOLD_REAL_COMPANY_EXPOSURE_COVERAGE、HOLD_PRE_1992_CALENDAR、HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION。
具体run按情况记录freshness、EXPOSURE_SELECTION、EVENT_FACT_REVIEW、HOLD_BUDGET_EXHAUSTED、HOLD_COST_PRICE_UNKNOWN、HOLD_INCOMPLETE_PREVIOUS_RUN、TIMEOUT、INVALID_SCHEMA、INVALID_REFERENCE、INVALID_NUMERIC_CLAIM、PROVIDER_UNAVAILABLE、PROMPT_INJECTION_REJECTED。

只开放Phase5已核实Metric数值定位；任意数字抽取/换算、真实模型语义可靠性、真实注入防护、真实用量/成本、全市场数据与Alpha均未验收。
Historical用途与本机记录时间分开，未实现公共历史模拟可用时间。真实Provider没有接入，不搜索密钥、不做Live smoke。

Issue #12保持OPEN，PR保持Draft。没有merge、Phase8、价格/定价、排名、推荐或交易；完成即停止等待人工复审。
