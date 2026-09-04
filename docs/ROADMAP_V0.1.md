# X V0.1 Roadmap

## Phase 0 — Foundation（当前）

- 冻结交易目标与 Decision-Time 规则
- 建立 Next-Morning 原子标签
- 建立未来函数硬门
- 建立执行 Universe 初始边界
- CI / pytest

## Phase 1 — Data Layer

- AKShare 交易日历、证券主数据、日线、分钟线适配器
- Raw -> normalized -> audited 本地缓存
- source_timestamp / fetched_at / schema_version
- 数据完整性和多源冲突审计

## Phase 2 — Decision Snapshot

- 14:35 / 14:45 / 14:50 全 Universe 快照
- 价格、VWAP、尾盘 10/20/30m、成交量/额、日内位置
- 行业相对强弱、市场横截面
- 严禁用 decision_ts 之后信息

## Phase 3 — Historical Dataset

- T 日 DecisionSnapshot 与 T+1 09:31—10:00 outcome 对齐
- 全 Universe，不只保存赢家或最终候选
- Point-in-time Universe 与公司行动处理

## Phase 4 — Qlib + LightGBM Baseline

- Alpha158 / Alpha360
- Return / Risk / Path 三类 baseline
- LightGBM Ranker（group = trade_date）
- Train / Valid / Locked Test + Walk Forward

## Phase 5 — Daily Morning Alpha Rank

输出 Top5 / Top20 / 全 Universe 审计表，同时保留 CASH 状态。

## Phase 6 — Forward Test

T 日冻结预测，T+1 10:05 后只结算；连续积累真实样本，检查 RankIC、TopK Edge、MAE、路径校准和 Alpha Decay。

## Phase 7 — Only if Edge survives

再考虑行业 Alpha、事件/公告、RD-Agent、深度模型和动态卖出模型。
