# Phase 6 Review Fix A1

接受基线：`eee9ba06ca44f7654dfa250ac3976dc41579acbd`。仅修订 PR #22 的当前知识、状态版本、反查、替代作用域和暴露选择契约。新策略版本为 `X_TRANSMISSION_V0.1_A1`；不进入 Phase 7。

## 当前知识与固定版本

所有检查先将 Ledger 按 `available_at <= request.as_of` 过滤。Event / Exposure 保留原有 stale 拒绝。Impact（包括显式 Impact 前提）、Resolution、Candidate 如果已有新版本，旧引用不能用于新经济路径，History 保存重算原因和触发原因的固定输入版本，状态为 HOLD。

Impact 的稳定身份为 object_id。Resolution 的研究上下文为 `(impact object_id, ontology object_id)`；Candidate 为 `(impact object_id, ontology object_id, rule object_id)`。重新解析产生新 object_id 也不能绕过同上下文新知识；按计算 as_of、available_at、版本和固定 ID 确定最新记录。上游修订但下游未重算，仍需 HOLD，不将旧结论默认搬到新版本。不同规则候选保持独立上下文。

使用的 EventStateSnapshot 必须对应 request.event_ref 的完整固定版本。存在旧 EventVersion 的 State 时保存其审计输入，但不使用其 Fact 状态，不填作当前 state_ref；路径和 History 标记 `EVENT_STATE_RECOMPUTE_REQUIRED` / HOLD。没有既有 State 的初始输入仍沿用已接受的 Event 契约。

新路径保存 state/resolution/relation/snapshot 固定引用。reverse 保留路径原计算值，并报告未完成重算；旧 PLAUSIBLE 不是新时点的当前结论。新增 EVENT_STATE、IMPACT、RESOLUTION、CANDIDATE、COMPANY、RELATION、SNAPSHOT 重算原因，保留 EVENT、EXPOSURE、SECURITY、ORIGIN 原原因。历史 as_of 不受后来版本影响。

## 替代公司查询

正式调用传 event_ref 或 history_ref，固定 industry_ref，仅检索 ECONOMIC world，并可进一步指定 candidate_ref / impact_ref / resolution_ref。多个机制但未明确上下文时拒绝。跨事件不能共享替代公司。

为保持原有测试和单事件调用，旧接口仅在可唯一推定事件及机制时允许省略作用域；多事件返回 `GRAPH_ALT_SCOPE_REQUIRED`，多机制返回 `GRAPH_ALT_MECHANISM_REQUIRED`。过期、HOLD 或选择不完整的历史不作为当前替代结果。该兼容入口不是跨事件扫描接口。

## 暴露选择完整性

保持 BuildRequest 固定输入，新增正式 `ExposureSelectionManifest`。引擎依据固定 ResearchUniverseSnapshot 内 INCLUDED 公司、Candidate 固定 industry_ref / path_role，枚举截止点最新已知经济 CompanyExposure。叙事关联不计入经济匹配。

清单记录匹配数、全部匹配固定引用、已选引用、排除引用及原因、选择策略、状态。Schema 强制已选/排除构成无重复且不相交的完整分割。未选中的已知匹配项明确标记 `OMITTED_BY_EXPLICIT_REQUEST_REVIEW_REQUIRED`；清单、History 和公司净评估 HOLD。个别已选路径的机制方向/原等级保留，不代表完整公司结论。reverse 报告选择不完整及后来出现匹配暴露的重算要求。

`COMPLETE_KNOWN_SUBSET` 仅表示本次已知子集完整；始终保留 `HOLD_REAL_COMPANY_EXPOSURE_COVERAGE`。工程能力完成不等于真实全 A 股业务覆盖完成。

## 兼容与存储

旧记录只在读取模型中获得可选字段默认值及 LEGACY_UNASSESSED，不改写不可变 raw 或旧历史。旧图缺少选择清单时，reverse 明确要求审查。A1 History 必须包含正式清单。复用既有 Schema 注册映射和 append-only Ledger，无新数据库表、SQL migration、依赖或许可证变化。

仅新增 Review 测试，不修改/删除/放宽原466项测试；Phase1–5、Market Engine、src/xalpha、PR #2均不修改。保留历史 Universe、真实业务覆盖、1992年前交易日历、sgmllib3k再分发许可证正文等既有 HOLD。无 Live、LLM、价格、排名或交易。

## 验证

2026-09-08，本地 Windows Python 3.11.9，复用已锁环境，按用户顺序全部离线运行：

```text
python -m pytest -q tests/test_phase6_graph.py tests/test_phase6_history.py tests/test_phase6_review_a1.py
56 passed in 111.28s (0:01:51)

python -m pytest -q
481 passed in 265.80s (0:04:25)

python -m pytest -q -m pit
153 passed, 328 deselected in 112.45s (0:01:52)
```

新增15项Review测试（其中12项PIT）；原466项测试文件无差异。覆盖研究链/前提修订、同上下文新解析ID、EventState错版本、后来CONTRADICTED、公司/归属/快照新知识、事件隔离与Event B独有公司、遗漏负向暴露、后来新增暴露及清单分割/JSON验证。

最终 focused、full、PIT 原始结果及四组 CI 在本次 PR #22 A1 修订记录中列出；仅全部通过后标记完成。Issue #11 保持 OPEN，PR #22 保持 Draft，等待人工复审。
