# X Data Contract V0.1

## DecisionSnapshot

每一行代表“某股票在某个真实决策时点能看到的状态”。一个交易日的批次必须包含 point-in-time Universe 中每个 symbol 的 14:35、14:45、14:50 三行；ST、停牌或数据不可用的股票也保留，只能标成 `tradable=false` 并给出 `unavailable_reason`，不得从分母中静默删除。

schema 固定为 `X_DECISION_SNAPSHOT_V0.1`，字段：

- trade_date
- symbol
- decision_ts
- price
- vwap
- ret_10m / ret_20m / ret_30m
- volume / volume_unit
- turnover / turnover_unit
- intraday_position
- volatility / atr
- industry_id
- stock_vs_industry
- market_context
- tradable
- unavailable_reason
- source
- source_timestamp
- feature_available_at
- fetched_at
- security_master_asof
- feature_schema_version

硬约束：

- `decision_ts` 必须带 `Asia/Shanghai` 时区且只允许 14:35 / 14:45 / 14:50。
- `source_timestamp <= decision_ts`。
- `feature_available_at <= decision_ts`；它是该行所有派生输入的最晚可用时间。
- `security_master_asof <= decision_ts`。
- `fetched_at` 是审计时间，历史抓取时允许晚于 `decision_ts`，但不得早于 `source_timestamp`。
- 任何 feature 无法证明可用时间时，必须 fail closed，不得进入快照。

完整校验由 `xalpha.snapshots.validate_decision_snapshot_frame` 执行。

## SourceBatch / audited cache

每次供应商响应同时保留：

- raw provider frame
- normalized frame
- dataset / source / endpoint / request params
- source_timestamp / fetched_at
- schema_version / units / availability_policy
- raw 与 normalized 的 SHA-256

cache partition 是不可变的。同一 partition 内容不同必须报错；读取前必须重新计算摘要。默认本地目录 `cache/` 不进入 Git。

## PointInTimeSecurityMaster

schema 固定为 `X_SECURITY_MASTER_V0.1`：

- symbol / name / exchange / board / status
- is_st / is_suspended
- listed_on / delisted_on
- effective_from / effective_to（左闭右开）
- available_at（当时可知时间）
- source / source_timestamp / fetched_at / schema_version

查询必须同时满足 effective-time 与 knowledge-time。AKShare 当前代码名称接口只生成“从本次抓取时刻起有效”的 current-only slice，不能回填历史。

## NextMorningOutcome

每一行对应 T 日一个 DecisionSnapshot，在 T+1 生成：

- next_open_return（若有可靠开盘价）
- next_0935_return
- next_0945_return
- next_1000_return
- open30_mfe
- open30_mae
- peak_to_trough_drawdown
- hit_plus_0_5 / 1_0 / 1_5
- hit_minus_0_5 / 1_0
- first_touch_plus_1
- first_touch_minus_1
- plus1_before_minus1
- time_to_mfe
- time_to_mae
- outcome_quality

## Selection-bias rule

训练数据原则上必须覆盖 T 日完整“可研究 Universe”，不能只保存模型最终入选票。

## Point-in-time rule

股票状态、行业归属、ST/停牌/上市状态等需要尽量使用 point-in-time 信息；禁止直接拿当前状态回填历史后假装当时已知。
