# Phase 1 Data Layer

## 边界

本数据层只属于 X。代码只依赖 Python 标准库、pandas、numpy 和 X 自身模块，不引用或读取任何旧炒股仓库、旧缓存、旧数据库或旧模型。

冻结目标不变：T 日尾盘真实可决策时点买入，T+1 09:31—10:00 研究可兑现路径；本阶段不训练泛化“次日涨跌”模型，也不声明存在可盈利 Alpha。

## AKShare adapter

`xalpha.data.AKShareAdapter` 提供四个 provider-neutral batch：

- trading calendar：`tool_trade_date_hist_sina`
- current-only security master slice：`stock_info_a_code_name`
- daily bars：`stock_zh_a_hist`
- minute bars：`stock_zh_a_hist_min_em`

AKShare 是 research optional dependency，模块在实际调用时才加载，因此默认 CI 不依赖外部网络。

每次调用返回 `DataBatch(raw, normalized, audit)`。raw 原样保留；normalized 只做明确列映射和类型规范化；audit 记录 endpoint、参数、抓取时刻、来源时刻、schema、单位和 availability policy。

### Fail-closed 语义

- 默认 `minute_timestamp_semantics=unverified`，分钟行的 `available_at` 为空，不能进入 Decision Snapshot。
- 只有独立验证供应商时间标签后，才允许配置为 `bar_end` 或 `bar_start`；`bar_start` 会再加 period，二者都可叠加非负 publication lag。
- AKShare `成交量` 默认记为 `provider_native_unverified`，不会擅自乘 100 或据此计算 share-based VWAP。
- 日线按“下一自然日 00:00 才可用”的保守策略标记，确保 T 日 14:50 不会读入 T 日完整日线。
- 当前代码名称表从抓取时刻才生效；它不是历史 security master。

## Audited local cache

`xalpha.data.AuditedLocalCache` 的布局：

```text
cache/<source>/<dataset>/<partition>/
  raw.table.json
  normalized.table.json
  audit.json
```

`audit.json` 绑定两个 payload 的 SHA-256。写入采用临时文件 + 原子替换，manifest 最后落盘；已有 partition 内容不同则拒绝覆盖。读取时先校验 manifest、审计元数据和两个摘要。

## Point-in-time security master

`PointInTimeSecurityMaster` 同时维护：

- effective time：证券状态描述哪个历史区间；
- knowledge time：这条记录何时可被当时的决策系统知道。

区间采用 `[effective_from, effective_to)`。同一 symbol 的有效区间不可重叠；查询默认把 knowledge cutoff 固定在决策时刻。Universe 包含 active、ST、停牌证券，执行资格在快照行上另行标记，不能先删掉失败样本。

## Decision Snapshot gate

`validate_decision_snapshot_frame` 要求一个交易日严格包含：

```text
point-in-time Universe × {14:35, 14:45, 14:50}
```

校验同时覆盖：完整性、重复行、时区、交易日、schema、非交易原因，以及 `source_timestamp`、`feature_available_at`、`security_master_asof` 三条未来信息通道。历史抓取的 `fetched_at` 可以晚于决策时刻，因为它不允许成为模型特征。

## 尚未宣称完成的事项

- 尚未把“接口能返回数据”当作字段单位和分钟标签语义已经验收。
- 尚未取得可覆盖历史名称、ST、停牌、上市/退市区间的权威 point-in-time 主数据源。
- 尚未进行在线全市场三时点抓取、速率、缺失率和稳定性验收。
- 尚未构建行业相对强弱与市场横截面特征。

这些事项完成前，可以继续做离线合成测试，但不能把数据层标记为 production-ready。
