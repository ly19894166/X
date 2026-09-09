# Phase 8 Review Fix A1

接受基线：`build/x-event-engine-phase8` @ `87cbb739e83a91235eca0ac5dfeba646f1e5f7a3`。
仅处理当前知识 freshness、模式隔离、Novelty 重算及 Next Buyer 机制绑定。原 656 项测试不修改；Phase 1–7、Market Engine 和工作流不改。

## 正式 current-knowledge identity

`pricing/freshness.py::semantic_scope` 是唯一 scope 实现。所有 key 带对象类型和 mode scope。固定 VersionRef 继续保存在输入中；scope 仅用于寻找截至 as_of 可知的后续修订，绝不作为动态 latest 正式引用。

| 对象 | semantic scope 的业务部分 |
| --- | --- |
| MarketObservation | instrument 稳定 ID、observation_type、window_start/end、source 稳定 ID |
| ProviderQualification | provider、source 稳定 ID、qualification scope |
| PricingContext | event 稳定 ID、security 稳定 ID |
| BenchmarkComposition | benchmark 稳定 ID、industry 稳定 ID（无行业为独立空范围） |
| AdjustmentBasis | instrument 稳定 ID、PRIMARY_PRICE_BASIS |
| MarketSession | instrument 稳定 ID、session_scope；旧 fixture 未指定时使用区间起始 UTC 日期的有序集合 |
| PricingPolicy | policy_version 代表的政策族 |

引用仍固定到版本；这里使用稳定实体 ID 是为了使 Source/Event/Security 的后续版本不能被当成全新实体范围。Provider 资格结论、成分列表、调整因子和规则参数不属于 scope，改变它们不会绕过 freshness。

MarketSession 新增可选 `session_scope`，用于明确命名一个日历/会话范围。calendar_version、timezone、offset、交易时段是修订内容，显式 scope 相同时改变这些值仍要求重算。旧 fixture 按覆盖日期区分历史 Session 和当前多日 Session，以免后补的历史时段误作当前日历修订。未来真实 provider 必须声明稳定 session_scope；本轮不增加真实 provider 或真实交易日历。未声明稳定 scope 的新 ID 若时段为空，或与既有范围重叠，无法证明它是独立日历范围，保守触发 MARKETSESSION_RECOMPUTE_REQUIRED。因此缩窄覆盖、删除交易时段或改变时区也不能静默绕过修订；明确不重叠的历史时段仍可独立保存。

同 scope、不同 object_id 的后续记录和同 ID 的版本更新均参与检查。即使新 ProviderQualification 为 PROVIDER_HOLD，也不能回退到旧 QUALIFIED。assess 输出 HOLD 和相应 `*_RECOMPUTE_REQUIRED`；current 返回旧记录及当前 HOLD，不回写旧结果。

PricingPolicy 不允许在当前模式下通过显式选择过期配置绕过修订。政策族内新对象/版本使旧输入要求重算。若需要旧政策结果，使用旧 as_of；不能把旧政策静默用于当前正式判断。

## 模式兼容政策

- ENGINEERING_FIXTURE 与 MOCK_FORWARD 属于同一个 FIXTURE_FORWARD freshness family；两者均为离线工程用途，不具备真实研究资格。
- HISTORICAL_REPLAY 仅参与 HISTORICAL_REPLAY freshness。
- REAL_FORWARD 是独立 family；不会被 fixture/Mock 记录刷新。本轮仍无法取得真实 provider/正式正向资格。

该政策同时约束 market_latest、通用 semantic lookup、相同 ID 版本 fallback 和 current 的市场输入扫描。模式不同但字段相同，不是当前模式的修订。历史研究中显式固定的既有前向输入不因后来前向发布而动态刷新；已有 Historical -> Forward 输入拒绝 Gate 保持不变。既有 Phase 7 research_mode / freshness Gate 保留。

## NoveltyDecision

current 检查当前 assessment 的固定 EventVersion 所关联 Evidence 稳定 ID。结果发布之后出现这些 Evidence 的新 NoveltyDecision（包括同一证据新 ID 的分类），返回 `NOVELTY_RECOMPUTE_REQUIRED` 并将 current_remaining_edge 设为 HOLD。无关 Evidence 不触发该原因。

NoveltyDecision 是 Phase 2 的公共证据知识对象，不新增 pricing_mode 或改写其契约。其自身 available_at 决定知识可见性；它不是 PricingEnvelope 的模式专属市场重放对象。旧 cutoff 仍为 AS_RECORDED，重算使用当时可知的分类，后来的 R1 不能保留旧 R4 正向结论作为 current。

## Next Buyer

维持既有 event/security/ECONOMIC/packet 引用 Gate，并新增精确路径约束：所有 supporting_path_refs 必须等于 request.path_ref。其他同证券经济路径也不能为本路径提供 buyer_good。

跨路径引用被保存为 WEAK，reason 为 `NEXT_BUYER_MECHANISM_MISMATCH`，不能据此产生 POSITIVE/STRONG。本轮不引入 CROSS_MECHANISM_BUYER 或自动等价机制推理。合法当前路径仍要求原有证据、观察、原文定位、触发和失败条件检查。

## 验收与边界

仅新增 `tests/test_phase8_review_a1.py`。测试覆盖六类新 ID 同 scope 更新、七类对象双向模式隔离、相同 ID 跨模式修订、R4→R1 Novelty PIT、无关 Novelty、显式 Session scope 及由既有 Graph 接口合法生成的两条 fixture 路径的 Buyer 绑定。

最终按 focused（包含原 Phase 8 和 A1）、full、独立 PIT 顺序运行。实际结果在完成后附下；原 Event Engine 四组 CI 的 run/job 原始日志回填 PR #24 / Issue #13。

无新增依赖。API_BUDGET=0；无真实行情/LLM API。原有八项永久 HOLD 与按输入产生的条件 HOLD 全部保留；formal_positive_remaining_edge 始终 false。PR OPEN/Draft、Issue OPEN；不 merge，不进入 Phase 9。

## A1 最终本地原始结果

```text
python -m pytest -q tests/test_phase8_pricing.py tests/test_phase8_pit.py tests/test_phase8_review_a1.py
109 passed in 253.20s (0:04:13)
```

新增 35 项测试，其中 31 项 PIT。原 656 项测试文件完全未改。

```text
python -m pytest -q
691 passed in 831.00s (0:13:50)
```

```text
python -m pytest -q -m pit
228 passed, 463 deselected in 374.42s (0:06:14)
```
