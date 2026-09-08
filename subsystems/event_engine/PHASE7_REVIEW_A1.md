# Phase 7 Review Fix A1

接受基线：b631931ec0e5ffd7133afcb500ddb6f7623fe3eb。
仅修订Phase7审计与机器契约，不修改Phase1—6及原551项测试。

## 决定来源

AnalysisRun.decision_source 为必填严格枚举：
PRIMARY / RED_TEAM / ADJUDICATION / HOLD_GATE。

- Primary选择保持：PRIMARY，final_result_ref=primary_result_ref。
- 无裁定且Red Team改变选择：RED_TEAM，final_result_ref=red_team_ref；包括NULL或合法ALT。
- 合法裁定完成：ADJUDICATION，final_result_ref=adjudication_ref。
- 运行失败或Gate阻断：HOLD_GATE，final_result_ref=null，final_hypothesis_id=null。先前模型结果只留在各自审计引用中。
- analysis_status=HOLD时，兼容既有final_choice=HOLD或降级NULL展示；NULL在这里是保护性回退，不是已通过研究的NULL假设。必须同时消费analysis_status/decision_source，禁止仅看final_choice。
- Schema检查来源引用，发布前validate_decision解析固定ModelResult检查hypothesis_id、choice及来源语义。不从Primary默认推断最终来源。

此字段不对旧审计记录猜测补值。A1前缺少decision_source的AnalysisRun不符合A1严格契约；不得改写旧raw记录或假装已迁移。需要迁移真实旧库时另行显式审核，当前只验收离线fixture。

## TARGET_WEAKENED

可信度下降但不足以改变正式选择；recommended_id必须等于primary.selected_id。
选择NULL需NULL_PREFERRED/TARGET_INVALIDATED，选择ALT需ALT_STRONGER。
引擎直接消费已通过该Gate的recommended_id，不再忽略矛盾推荐。

## 评论与正式事实

以下自由文本均固定为INFERENCE_ONLY / RESEARCH_COMMENTARY，无FACT资格：
Hypothesis.assumptions/failure_conditions/unknowns/reasoning_summary_zh；
RedTeam.challenges_zh/failure_conditions_zh/reasoning_summary_zh；
Adjudication.reasoning_summary_zh。
Schema含此说明，中文报告也明确标注；原文只作为审计评论保存。

downstream_input从后续Red Team/Adjudication模型上下文中剔除这些评论以及alternative_search_gap_zh。
不把评论转成Evidence，不补supporting_evidence_refs，不扩充Packet。
保留结构化假设、引用、数值和带kind的ResearchStatement，供后续核查。
后续阶段的事实消费必须遵守同一边界；本轮不实现Phase8。

正式事实声明统一使用既有ResearchStatement，Primary保持原Hypothesis结构；
RedTeamReport/Adjudication仅新增默认空statements字段。
CONFIRMED_FACT / COUNTEREVIDENCE仍必须通过Packet内EvidenceRef、FACT、VALIDATED、固定原文摘录完全匹配Gate。
推断、假设与未知仍保留各自kind，不成为已确认事实。
未开发通用NLP或扩充正则事实分类器；原有数值、引用及注入Gate保持。

固定Packet内不存在新的外部Evidence。TARGET_INVALIDATED之后，裁定器选择TARGET会INVALID_REFERENCE，
无合法裁定发布，最终HOLD_GATE；自由评论和重复引用既有Evidence不能复活失效TARGET。
需要新事实时须先形成新PIT Packet及新研究run，不修改旧结论。

## 成本与范围冻结

ALPHA未验证前 API_BUDGET = 0。
只有MockModelProvider，不实现真实Provider、API调用、ChatGPT浏览器自动化或Manual ChatGPT Bridge。
Mock的请求/token预算仅为工程模拟，不是收费API授权。
未来“X自动计算 + 人工ChatGPT Plus / Sol研究 + 结构化导回”的Bridge留待独立Shadow/Forward阶段。

无新依赖、许可证变更或数据库迁移。
持续保留HOLD_MODEL_PROVIDER_LIVE、HOLD_MODEL_USAGE_COST_UNVERIFIED、
HOLD_HISTORICAL_UNIVERSE_COVERAGE、HOLD_REAL_COMPANY_EXPOSURE_COVERAGE、
HOLD_PRE_1992_CALENDAR、HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION。
其他freshness/预算/超时/Provider/Schema/引用/数值/崩溃恢复隔离继续有效。

## 验证

新增tests/test_phase7_review_a1.py，不改原551项测试。
最终focused/full/PIT原始结果与本HEAD四组CI结果回填PR #23、Issue #12。
PR保持Draft，Issue保持OPEN；不合并、不进入Phase8。
## A1最终本地原始结果

Windows Python 3.11.9，复用既有锁定环境，100% offline fixture。
按focused → full → PIT执行：

    python -m pytest -q tests/test_phase7_research.py tests/test_phase7_pit.py tests/test_phase7_review_a1.py
    101 passed in 303.96s (0:05:03)

    python -m pytest -q
    582 passed in 545.07s (0:09:05)

    python -m pytest -q -m pit
    172 passed, 410 deselected in 227.53s (0:03:47)

新增31项测试，其中2项PIT。原551项测试未修改，全部回归通过。
四组远端CI以PR #23 / Issue #12中本次提交的实际结果为准。