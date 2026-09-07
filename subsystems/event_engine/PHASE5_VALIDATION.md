# Phase 5 本地验收记录

基线：`build/x-event-engine-phase4` /
`8b74a3a432da8cb6ca16781f614bd5114119585a`。
范围：Issue #10；输入契约与边界见 [PHASE5.md](PHASE5.md)。
本文件记录提交前本地验证，远端四组 CI 的最终结果与 job 链接记录在 Phase 5 Draft PR 正文，
避免为了更新运行状态而重复触发同一代码的 CI。

## 原始结果

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
