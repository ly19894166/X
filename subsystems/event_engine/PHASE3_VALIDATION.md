# Phase 3离线工程验收

日期：2026-09-06。输入基线：`f624bf53c933f779a7e797a176ca96d3d5ce2766`。
分支：`build/x-event-engine-phase3`；base：`build/x-event-engine-phase2`。
Issue #7已由用户关闭，Issue #8明确授权Phase3；不重做Phase1/2或重新搜索开源项目。

## 最终本地原始结果

本次只修PR #19第一轮人工Review的三个阻塞项，修订基线`9e9f31768e75d418f8bb4b32f767e5d67e2288eb`。
原交付222/80为修订前结果，以下为本次代码的重新验证结果。

Windows / CPython3.11.9，复用Phase2虚拟环境，仅将PYTHONPATH指向本工作树src，未重装依赖：

```text
python -m pytest -q tests/test_phase3_review.py
8 passed in 7.18s

python -m pytest -q
230 passed in 96.23s (0:01:36)

python -m pytest -q -m pit
87 passed, 143 deselected in 23.57s
```

230=Phase1/2原158项+Phase3原64项+本次8项；87项PIT为总数子集（本次新增7项）。
新增11个版本Schema均能导出JSON Schema，数据库历史JSON round-trip通过。
测试全过程禁止真实socket连接；中文state-fixture通过CLI测试。

## 本次Review修订证据

| 阻塞项 | 最小修订与对应测试 |
|---|---|
| R5不能自动改Fact | 移除qualified_r5/new_r5捷径；已验证二手/一手R5均保持PLAUSIBLE并P0/HOLD，显式COUNTEREVIDENCE才降级。test_verified_r5_requires_explicit_semantic_assessment两例；原material clock与cooldown测试同步改断言 |
| later合源重算 | confirm_origin与ORIGIN_RELATION_CHANGE/P1/READY任务同事务；所有受影响事件排队，不受传播冷却；同键幂等和无变化确认不重复任务。test_later_origin_confirmation_queues_immediate_recompute_and_preserves_asof；2源→1源后沿原CONTRADICTED/HOLD，旧as_of不变 |
| 合源故障恢复 | test_origin_confirmation_task_atomic_recovery两例：事务内故障全部回滚；提交后中断按原回执恢复，最终只保留一簇确认与一条对应任务 |
| provenance同域 | test_dimension_provenance_and_support_summary_share_exact_subset、test_no_support_has_no_origin_summary_provenance：SUPPORT的count/source/cluster/evidence同域，FACT/PRICING/两窗NARRATIVE分别引用真实输入，全事件输入仅留审计refs |
| profile来源范围 | test_narrative_provenance_includes_used_profile_but_not_other_topic：对应主题画像证据保留于NARRATIVE，其他主题/FACT/PRICING不混入 |

二手R5用版本化NoveltyDecision离线fixture验证StateEngine输入边界；未改变Phase2确定性分类器。
原真实结构化R5摄取、material刷新与未知来源测试继续通过。无Live或语义自动核验宣称。

## 验收证据对应

| 要求 | 测试证据 |
|---|---|
| 高传播传闻不确认事实、QUIET→RAPID、CROWDED+UNVERIFIED | test_rumor_rapid_diffusion_does_not_confirm_fact、test_crowded_rumor_and_time_decay_never_invalidates_fact |
| 官方一步确认、不会自动实施、新执行材料 | test_official_confirmation_then_new_implementation、test_intent_cannot_become_fact、test_official_tier_and_quote_required |
| 同source多Origin与不同source区分 | test_fact_confirmation_uses_supporting_independent_sources；原Phase2 70转载/PIT确认测试保留 |
| 未核验传闻或仅部分主张不增加完整确认来源数 | test_unassessed_independent_rumor_not_support、test_partial_claim_is_not_second_full_independent_confirmation |
| 官方否认、证伪、强反证、矛盾不偏向利好 | test_negative_evidence_p0_not_bullish、test_unresolved_contradiction_cannot_select_later_favorable_claim |
| 新一手/R5触发不等于事实等级 | test_new_primary_triggers_research_without_automatic_fact_upgrade、test_unverified_r5_is_trigger_not_automatic_fact_grade |
| 七种价格fixture、缺数据UNKNOWN、证券明细分离、上涨不确认事实 | test_price_dimension_fixture_never_confirms_fact、test_missing_and_mixed_prices_are_unknown_with_security_details |
| 官方确认与NO_REACTION共存 | test_official_and_no_reaction_can_coexist |
| R1/R2/UNDETERMINED不刷material，R3/R4/R5刷新 | test_material_clock_inherited_from_phase2；原Phase2对应六类测试保留 |
| 实际事件年龄与发现/实质更新年龄分离 | test_event_age_and_material_age_separate |
| MERGE/SPLIT保留父ID、child不进旧as_of | test_lineage_asof_parent_ids_and_children |
| ARCHIVE不删除/否定，归档后新material复活 | test_archive_reactivate_new_material_preserves_old_world |
| MUTATE需要R4、DNA/版本可改变且旧历史保持 | test_mutate_requires_r4_and_keeps_version |
| 触发幂等、expected_version、冷却归并最新输入 | test_recompute_idempotency_and_expected_version、test_cooldown_coalesces_diffusion_but_denial_is_immediate |
| R5绕过冷却、跨资产仅fixture | test_r5_bypasses_cooldown、test_cross_asset_trigger_is_fixture_only_and_not_fact |
| 未来规则/画像/确认/否认不回填 | test_new_policy_does_not_backfill_history、test_profile_sample_and_followers_do_not_confirm_fact、test_rumor_confirmation_denial_timeline_and_replay |
| 全转换/禁止表、严格未知状态 | test_explicit_tables_cover_every_pair、test_forbidden_table_and_unknown_state_fail_closed |
| 原子回滚、提交后恢复、Replay一致 | test_atomic_state_rollback、test_lineage_crash_rolls_back_all_children、test_state_commit_crash_recovery_keeps_original_visibility、test_restart_replay_and_json_roundtrip |

## CI与边界

既有Event Engine四组工作流继续Windows/Ubuntu×Python3.11/3.12，运行全量、PIT、Phase1/2中文fixture、Phase2 Replay以及新Phase3 fixture。
最终提交SHA和各组原始日志写入对应Draft PR；本文本地PASS不替代远端结果。

没有新增依赖或许可证；SQLAlchemy/Pydantic/pytest等复用既有锁。没有DB Schema迁移、重构Phase2事务层或真实采集扩展。
HOLD：人工语义/负责机构权限仍需人工核验；叙事阈值、生命周期为未校准离线规则；真实行情、24小时覆盖、金融有效性未验证。
保留sgmllib3k `HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION`，未做Live smoke，未调用模型或付费API。
Market Engine、src/xalpha、原Market CI/labels/models、PR #2、Issue #1及冻结开源矩阵未修改。
Issue #8保持OPEN，等待人工复审；不自动合并、不进入Phase4。
