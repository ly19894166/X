# X Provider Qualification V0.1

## 目标

X 不是高频或自动交易系统。数据源不要求毫秒级，但必须做到：

1. 延迟在分钟级且可审计；
2. 时间语义明确；
3. 历史回放与实时运行使用同一可见信息边界；
4. 数据源失败时不得用陈旧数据静默冒充实时数据。

## Freshness 工程阈值

当前 V0.1 默认：

| 数据年龄 | 状态 | 正式决策默认处理 |
|---|---|---|
| <= 60 秒 | FRESH | 可用 |
| 60-180 秒 | ACCEPTABLE | 可用 |
| 180-300 秒 | STALE_WARNING | 默认不用，只保留人工/审计 |
| > 300 秒 | STALE_REJECT | 拒绝 |

阈值是工程配置，不是市场事实。必须通过 Forward 运行结果再校准。

## Provider 路由

正式路由固定：

`PRIMARY -> BACKUP -> CACHE -> FAIL_CLOSED`

每一层都必须重新检查 source/event time 和 staleness。网络调用成功不等于数据可用于决策。

## 当前候选矩阵

| 角色 | Provider | Endpoint | 用途 | 当前状态 |
|---|---|---|---|---|
| Primary candidate | AKShare / EastMoney | `stock_zh_a_spot_em` | 全市场尾盘横截面快照 | UNVERIFIED |
| Primary candidate | AKShare / EastMoney | `stock_zh_a_hist_min_em` | 单股 1 分钟 | UNVERIFIED |
| Backup candidate | AKShare / Sina | `stock_zh_a_minute` | 单股分钟备用 | UNVERIFIED |
| Cross-check candidate | Longbridge | quote/candlestick/intraday | TOP 候选实时复核 | 尚未接入 X runtime |

### 为什么当前仍是 UNVERIFIED

- EastMoney 全市场快照没有已独立验证的 provider event timestamp；接口能返回数据不代表可以证明该值在 Decision Time 前已经可见。
- EastMoney 分钟线仍需要独立确认 bar-start / bar-end 语义、发布延迟和成交量/成交额单位。
- Sina 分钟时间字段会原样保留，但在语义验收前 `available_at` 为空，不能通过 Decision Snapshot gate。
- Longbridge 后续只考虑作为 TOP 候选交叉验证，不作为第一阶段全市场历史数据源。

## Benchmark 记录字段

`xalpha.data.benchmark` 记录：

- provider
- dataset
- symbol
- requested_at
- event_time
- provider_time
- received_at
- request_latency_seconds
- staleness_seconds
- freshness_status
- success / timeout / parse_error
- row_count
- error_type / error_message

真正重要的是 Information Age，而不是单纯 HTTP RTT。

## Offline Replay

网络不稳定不得阻塞开发。`ReplayProvider` 使用完整 `DataBatch` fixture 运行：

`Provider -> Audit -> Cache -> Snapshot -> T+1 Label`

Replay 必须保留原来的 source_timestamp / availability metadata，禁止把历史文件抓取时间伪装成当年实时可用时间。

## PASS 门槛

一个实时 Provider 只有在至少完成以下验收后才可从 UNVERIFIED 升级：

- 时间字段语义已确认；
- 单位已确认；
- 至少多个交易日实测稳定性；
- P50 / P95 staleness 有记录；
- 缺失率、超时率和解析错误率有记录；
- 实时抓取与事后数据可交叉核对；
- 历史 replay 不使用真实 Decision Time 后才会获得的数据。

在上述门槛通过前，X 不进入 Qlib / LightGBM 正式训练。
