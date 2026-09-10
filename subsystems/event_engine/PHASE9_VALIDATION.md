# Phase 9 工程验收记录

接受基线：build/x-event-engine-phase8 @ 3faa618922e6e5075a4edc3e8054a9368a1acca6。
分支：build/x-event-engine-phase9。仅 Issue #14，完成后等待人工复审。

## 测试范围

新增 69 项 Phase 9 测试：分级、原维度 ordinal、UNKNOWN、固定上游 Gate、账户/未来标签字段拒绝、全样本/空榜、世界分离、稳定 tie-break、同证券多事件/多路径、负向路径、不同 ID semantic freshness、Historical/Forward 隔离、publication fence、版本降级、崩溃回滚。
原 Phase 1–8 的 691 项测试源文件未修改。测试沿用全局 socket.connect 拦截，100% 虚构离线 fixture。

## Focused 原始结果

主 focused：

```text
python -m pytest -q tests/test_phase9_ranking.py tests/test_phase9_pit.py tests/test_phase9_package.py
67 passed in 1080.72s (0:18:00)
```

最终审计补充（新增历史包与同身份追加版本用例后）：

```text
python -m pytest -q tests/test_phase9_pit.py -k 'historical_package or append_only'
2 passed, 16 deselected in 26.77s
```

最终 full 包含以上全部 69 项，不以分段 focused 代替全量验收。

## Full / PIT

python -m pytest -q

760 passed in 1883.58s (0:31:23)

python -m pytest -q -m pit

246 passed, 514 deselected in 447.02s (0:07:27)

## 四组 CI

Event Engine 原四组 Ubuntu/Windows × Python 3.11/3.12 矩阵保留。检查全量、PIT、Schema、全部 Phase 2–9 fixture；增加 Phase 9 中文机会包。最终精确提交 SHA、run URL、各 job 原始结果登记于本次 Draft PR / Issue #14。未完成四组前，不报告工程完成。

## 端到端工程样本

9 个虚构事件、1 个虚构证券、27 条路径级样本。实际分布：ALPHA1=2、ALPHA2=2、BETA=1、WATCH=8、OVERPRICED=1、REJECT=13，其中 HOLD=7（处理状态与等级交叉统计，不重复加入总数）。9 条负向机制均保留；空机会榜合法；Universe 分母与 path 样本数分别报告。

ENGINEERING_DEMO / NO_ALPHA_CLAIM / NO_INVESTMENT_ADVICE；所有 formal_live_alpha=false。

## 增量与边界

新增 ranking 包、三份测试和 Phase 9 文档；Ledger/CLI 仅 Schema 注册，CI 仅名称和新离线 fixture 接入。不修改旧测试、旧 Gate、依赖锁、src/xalpha/、Market Engine、main。不合并任何 PR。不实现 Phase 10。

零新增依赖、零新增第三方许可证。GitHub 用于代码交付和 CI；没有真实行情、模型、Broker API，没有 API Key/secret 查找或写入，没有收费模型调用。API_BUDGET=0。

## 保留 HOLD

- HOLD_MODEL_PROVIDER_LIVE
- HOLD_MODEL_USAGE_COST_UNVERIFIED
- HOLD_MARKET_DATA_PROVIDER_LIVE
- HOLD_PRICING_POLICY_CALIBRATION
- HOLD_RANK_POLICY_CALIBRATION
- HOLD_HISTORICAL_UNIVERSE_COVERAGE
- HOLD_REAL_COMPANY_EXPOSURE_COVERAGE
- HOLD_PRE_1992_CALENDAR
- HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION

此外保留每个样本的具体输入/缺失/freshness HOLD，以及 HOLD_REAL_FORWARD_QUALIFICATION。工程分级和成功 CI 不消除这些真实研究资格限制。
