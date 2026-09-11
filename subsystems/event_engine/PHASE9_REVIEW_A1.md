# Phase 9 Review Fix A1

接受基线：build/x-event-engine-phase9 @ c1dc74ed80b1f186ca247f1e7d3c2a66084d7779。仅修复人工复审四项；不修改Phase1–8实现或原760项测试，不进入Phase10。

## 修复

1. BETA_UNKNOWN_POLICY=CORE_KNOWN_COMPANY_BUYER_OPTIONAL。五个核心维度Remaining Edge/Thesis/Price-in/Crowding/Reversal不得UNKNOWN/HOLD；policy与持久化CandidateVersion双重约束。Next Buyer是明确公司级可选项，非其余维度的豁免。
2. PURITY_METRIC_SCOPE由固定TransmissionPath计算(exposure_ref,REVENUE_SHARE)，不依赖已有metric_refs或ResearchPacket内是否曾存在收入指标。current检查package.as_of后该scope的全部发布，覆盖0→1、1→新版、冲突口径、多口径变化及失效修订。重建从合法Phase5固定指标选择当时各会计口径最新发布；唯一VERIFIED/DEFINED才确定纯度，多口径UNKNOWN。所有实际使用的指标固定写入结果引用，不改写Phase7事实或结论。
3. 同一History ID的多个version拒绝RANK_HISTORY_VERSION_AMBIGUITY。不同History ID的重复event/security/exposure/world/candidate/resolution机制整体拒绝RANK_AMBIGUOUS_SCOPE，事务不留部分排名；合法不同事件或机制继续允许。
4. V0.1 grade_order精确冻结为GRADE_ORDER，Schema禁止重排；CandidateChange和正式排序共用该来源。等级与rank位置变化继续独立。

## 测试与兼容

新增17项Review测试，原760项不修改。覆盖BETA五维UNKNOWN及显式买方例外、持久化Schema、非法等级重排、升降级与名次独立、History输入顺序/旧版/新版、首次0.72收入比率、冲突与多口径修订。

可选多证券测试：通过既有Registry/Graph/Ranking接口生成2家公司、3个证券、多条路径；验证完整样本、SecuritySummary、向量顺序打乱、空经济榜与执行资格展示隔离。未捏造各证券独立研究/定价；这些缺口保持HOLD。此用例不宣称新增多证券正向Alpha验收。

既有Phase9 BETA工程fixture补入连续交易与同窗口量额数据，原Phase8引擎据此产生已知THIN及风险维度，维持合法BETA示例；不修改原测试断言，不填造派生Pricing。

## 验证结果

Phase9 focused + Review A1：

```text
86 passed in 1288.39s (0:21:28)
```

最终History整体拒绝检查补充后，Review A1全量补跑：

```text
17 passed in 56.17s
```

Full：`777 passed in 2154.62s (0:35:54)`

PIT：`249 passed, 528 deselected in 548.65s (0:09:08)`

精确提交HEAD的四组CI原始结果在PR #25与Issue #14登记。四组未成功前不报告Review完成。

## 边界

零新依赖/许可证。API_BUDGET=0；无真实行情/LLM/Broker调用，无未来Outcome、收益、回测或Phase10。Market Engine、src/xalpha/、main未修改。PR #25保持OPEN/Draft，Issue #14保持OPEN；无merge/force push。

保留HOLD_MODEL_PROVIDER_LIVE、HOLD_MODEL_USAGE_COST_UNVERIFIED、HOLD_MARKET_DATA_PROVIDER_LIVE、HOLD_PRICING_POLICY_CALIBRATION、HOLD_RANK_POLICY_CALIBRATION、HOLD_HISTORICAL_UNIVERSE_COVERAGE、HOLD_REAL_COMPANY_EXPOSURE_COVERAGE、HOLD_PRE_1992_CALENDAR、HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION、HOLD_REAL_FORWARD_QUALIFICATION及逐输入缺失/重算HOLD。formal_live_alpha=false。
