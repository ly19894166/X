# Phase 5 本地验收记录

基线：`build/x-event-engine-phase4` /
`8b74a3a432da8cb6ca16781f614bd5114119585a`。
范围：Issue #10；输入契约与边界见 [PHASE5.md](PHASE5.md)。
本文件记录提交前本地验证，远端四组 CI 的最终结果与 job 链接记录在 Phase 5 Draft PR 正文，
避免为了更新运行状态而重复触发同一代码的 CI。

## 初始提交83066d5的原始结果（Review后结果见文末）

Windows / Python 3.11，复用独立 Event Engine 已锁环境，通过 PYTHONPATH 指向本分支 src。

```text
python -m pytest -q tests/test_phase5_registry_exposure.py
88 passed in 49.29s

python -m pytest -q
398 passed in 164.21s (0:02:44)

python -m pytest -q -m pit
119 passed, 279 deselected in 42.92s
```

Phase 1–4 接受基线共 310 项，全部保留；本阶段增加 88 项。
PIT 从 102 增至 119 项。测试全部离线，禁止真实 socket。

覆盖：公司与 A/H 证券分离、名称/代码变化保持公司身份、五类 A 股板块、
ST/*ST/停牌保留、无执行权限过滤、前导零、身份冲突/HOLD 隔离、
角色和指标类型分离、零/负/缺失分母、新闻及叙事不能默认直接暴露、
关键词只待核验、未知暴露逐项覆盖、不同知识版本重述、确定性回放、
Schema/JSON round-trip、提交前后与回执后的故障恢复。
全部八类新对象均生成 JSON Schema 并 round-trip。

## 四个时间场景

- A：2025 年报于 2026-03-28 首次可知；2026-01-15 无业务数据，2026-03-29 可见。
- B：更名前后返回各自 SecurityVersion；Company ID 不变。已知未来更名在生效前不遮蔽旧名。
- C：退市后当前分母排除；退市前旧快照仍包含。
- D：收入占比从 0.3 更正为 0.2；旧时点仍 0.3，重述后尚未重新核验的旧指标不沿用。

## 中文 fixture 原始关键输出

```json
{
  "能力": "ENGINE SUPPORTS FULL-A-SHARE RESEARCH UNIVERSE",
  "历史覆盖": "HOLD_HISTORICAL_UNIVERSE_COVERAGE",
  "真实业务覆盖": "HOLD_REAL_COMPANY_EXPOSURE_COVERAGE",
  "年报晚披露": {"一月可见暴露": 0, "三月可见暴露": 1},
  "公司ID": "CO_FIXTURE_A",
  "A股代码": "000001",
  "收入占比": 0.3,
  "结论": "工程能力完成 ≠ 全 A 股真实数据覆盖完成。"
}
```

覆盖报告样例：研究证券 1、公司 1、归属 1、直接暴露公司 1，其他暴露计数 0；
另有两个公司仅一个可靠暴露的测试，未知公司逐项显示，未自动填充。
此数据为虚构工程样例，不能用于市场覆盖率声明。

## 隔离、依赖与 HOLD

- 无新依赖、无依赖锁/哈希/许可证变更。
- sgmllib3k：保留 HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION。
- 无数据库 DDL 迁移，仅向已有 append-only records 注册八种领域记录。
- 已通过 Phase 1–4 代码仅 CLI 注册/fixture 命令与 Ledger 模型注册有增量。
- CI 只更新 Event Engine 独立工作流，保留 Windows/Linux × 3.11/3.12。
- Market Engine、src/xalpha/、其 security_master、Market CI、PR #2、Issue #1 未修改。
- 真实 PIT 证券身份/全 A 股覆盖未验收；真实公司暴露全覆盖未验收。
- 法律实体连续性不明为 REVIEW_REQUIRED/HOLD，证券冲突逐项隔离。
- 1992 年前证券日历 HOLD；未知/异常指标 UNDEFINED/HOLD。
- 没有 Live smoke、网络采集、LLM、股票价格/推荐/排名、Transmission Graph 或 Phase 6。

Issue #10 保持 OPEN；PR 保持 Draft，等待人工复审。

## PR #21 人工 Review 修订验收（本轮最新结果）

修订基线：`83066d525d1f110a8375f43b3dbd85b38a3eb97d`。
仅处理三个阻塞项，未修改 registry、Ledger、Phase 1–4、Market Engine 或 CI 配置。

1. IndustrySegment 与 CompanyExposure 的现实区间按左闭右开求重叠，完全不重叠拒绝。
   不再用墙钟判断产业现实适用性。2026-01-01 退役的固定产业版本允许
   2026-03-28 晚披露的2025业务引用，旧as_of不可见；固定输入PIT门槛不变。
2. VERIFIED数值新增分子/分母独立 MetricSourceSpan：
   quote、basis_text、value_text、value_offset。校验不可变raw、数值等值和完整数字边界，
   包括quote外的百分号/指数，拒绝凭reviewer补造30/100。
   正式披露及一手FACT/VALIDATED Gate通过后才能VERIFIED；新闻/叙事/二手/PARTIAL保留SUPPORTED/HOLD。
   30/100→20/100 更正保存新原文片段，旧时点数字及Evidence引用不变。
3. 采用方案A：EXACT_ALIAS_REVIEWED / VERIFIED_RULE 不属于本Phase可用枚举。
   VERIFIED_DIRECT只开放MANUAL_VERIFIED，仍需具名reviewer和正式披露。
   later alias/rule revision不改变旧人工暴露的固定产业版本。

原始本地结果（Windows/Python3.11，现有已锁环境）：

```text
python -m pytest -q tests/test_phase5_registry_exposure.py tests/test_phase5_review.py
115 passed in 66.80s (0:01:06)

python -m pytest -q
425 passed in 178.51s (0:02:58)

python -m pytest -q -m pit
126 passed, 299 deselected in 50.55s
```

原398项回归全部保留；新增27项阻塞回归，PIT119→126。
原异常比例/负利润样例补充真实的虚构原文定位，没有放松异常数值规则。
四组远端CI以本次提交的PR检查和PR正文job链接为准，不用初始提交的CI冒充本次结果。

兼容性：旧fixture中缺失VERIFIED数值原文定位或使用未实现映射方法的记录会FAIL_CLOSED，
不自动生成/回写provenance。旧库可用原基线审计；新契约在新隔离fixture库验收，
未实现旧库自动迁移。无新依赖、无Live、无LLM、无价格/排名/交易。
全部真实覆盖HOLD及sgmllib3k许可证HOLD保持。Issue #10 OPEN、PR Draft，等待人工复审，不启动Phase 6。
