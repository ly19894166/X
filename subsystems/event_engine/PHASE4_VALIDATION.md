# Phase 4工程验收记录

日期：2026-09-07。Issue #9；接受Phase3基线`8469ea722e65cc0f6975b3be0ed88b5fb5d9767d`。
分支`build/x-event-engine-phase4`，stacked base为`build/x-event-engine-phase3`。
开始前确认Issue #8 CLOSED、PR #19 HEAD一致/四组CI SUCCESS、工作区干净；未重新研究架构或开源项目。

## 本地原始测试

Windows / CPython 3.11.9；复用Phase2虚拟环境，PYTHONPATH指向本工作树src。没有安装或更新依赖。

```text
python -m pytest -q tests/test_phase4_ontology.py
64 passed in 13.37s

python -m pytest -q
294 passed in 108.84s (0:01:48)

python -m pytest -q -m pit
97 passed, 197 deselected in 28.50s
```

294 = Phase1–3既有230项 + Phase4新增64项；97项PIT为总数子集（原87 + 本次10）。
9个新增版本Schema可生成JSON Schema；新增及既有历史JSON round-trip通过；全部测试由既有fixture禁止真实socket。

## Issue #9测试对应

| 要求 | 对应证据 |
|---|---|
| DEMAND+UP唯一存储，非法同义枚举拒绝 | test_demand_has_one_canonical_representation四种短语；test_unknown_internal_classifications_rejected |
| FX明确pair/direction/报价 | test_fx_pair_direction_and_quote_required六类错误；test_fx_canonical_pair_roundtrip；test_fx_resolver_does_not_confuse_inverse_pair |
| SUPPLY DOWN与PRICE UP分离 | test_supply_observed_and_price_hypothesis_are_separate |
| OBSERVED/HYPOTHESIS不混用 | test_hypothesis_cannot_masquerade_as_observation；test_non_fact_raw_material_cannot_be_observed四类主张 |
| 原文核验、中文机制必填 | test_observed_quote_and_chinese_mechanism_required |
| 产业树循环/悬空/层级/重复/有效期 | test_industry_tree_rejects_invalid_structure五类；test_stable_ids_cannot_be_reused_for_different_role |
| unknown/歧义alias保持UNRESOLVED | test_late_alias_never_backfills_old_asof；test_ambiguous_alias_is_unresolved |
| 10:30不见11:00新增alias；显式旧manifest不读latest | test_late_alias_never_backfills_old_asof；test_phase4_chinese_cli_fixture |
| crosswalk追加且保留旧版本/代码前导零 | test_crosswalk_changes_are_append_only；test_unresolved_crosswalk_and_old_version_are_explicit |
| Theme不是Industry或Impact；只有主题证据不强行经济映射 | test_narrative_theme_cannot_be_industry_or_impact；test_theme_name_cannot_be_used_as_industry_identity |
| 一个Impact同时正负产业候选 | test_positive_negative_candidates_determinism_and_old_ontology |
| 固定输入确定性、新本体不改变旧replay | 同上；相同请求精确幂等、不同请求业务候选一致 |
| 无证据映射不能VERIFIED | test_mapping_cannot_be_verified_without_evidence；test_verified_rule_still_outputs_hypothesis_candidate |
| 前提HOLD与证据不能被下游消除 | test_premise_hold_and_raw_provenance_cannot_be_laundered |
| effective不是available，未来Impact/映射不进旧as_of | test_pit_effective_date_is_not_knowledge_time；test_late_impact_and_mapping_not_visible_at_old_cutoff |
| 原子本体发布/恢复与候选回滚 | test_ontology_atomicity_and_recovery两类故障；test_resolution_rollback_has_no_partial_candidates |
| Event及三状态不得反向修改 | test_phase4_never_modifies_event_or_three_states；中文CLI fixture中同样断言 |
| JSON Schema与历史round-trip | test_phase4_json_schema九类；test_phase4_never_modifies_event_or_three_states |
| Phase1–3回归 | 原230项全部继续通过，未修改既有测试 |

## CI与停止边界

独立Event Engine CI保留Windows/Ubuntu × Python3.11/3.12；全量、PIT、依赖检查、既有三份fixture全部继续执行，
仅新增Phase4中文ontology-fixture。最终SHA、四组状态和各组原始测试日志记录于本Phase的Draft PR；本地PASS不替代CI。

无新依赖、无DB schema迁移；Ledger只注册新模型，CLI只扩展schema列表和新命令。
Market Engine、src/xalpha、原Market CI/labels/models、PR #2、Issue #1、PR #19接受基线及冻结开源矩阵均未修改。

HOLD：本体/规则/外部crosswalk仅虚构fixture，未证明产业覆盖或经济有效性；目标对象词表有限；
原文语义和同ID身份维护仍需人工核验；不声称自动事实理解、真实分类授权或已校准confidence。
没有Live、采集、真实行情、LLM、公司/股票映射、排名或交易。保留sgmllib3k `HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION`。
Issue #9保持OPEN，PR保持Draft；工程验收不等于人工复审通过。停止于Phase4，不启动Phase5。
