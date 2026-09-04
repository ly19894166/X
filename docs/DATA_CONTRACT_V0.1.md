# X Data Contract V0.1

## DecisionSnapshot

每一行代表“某股票在某个真实决策时点能看到的状态”。最低字段：

- trade_date
- symbol
- decision_ts
- price
- vwap
- ret_10m / ret_20m / ret_30m
- volume / turnover
- intraday_position
- volatility / ATR
- industry_id
- stock_vs_industry
- market_context
- tradable
- source
- source_timestamp
- feature_schema_version

任何不能证明在 `decision_ts` 前可获得的字段，默认不得进入训练。

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
