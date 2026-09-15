# X REAL LANDING V0.1

接受基线：453c08940eca12cab1d82086a8344acae34163ce；Phase10 exact-head 四环境CI SUCCESS（run 34793063529）。
状态：PHASE10_REVIEW_ACCEPTED / ENGINEERING_SHADOW_READY。独立落地层，不修改Phase1–10业务语义。

| 层级 | 目标 | 本轮状态 |
|---|---|---|
| L1_REAL_EVENT | 真实来源→RawObservation→Evidence→Origin→Novelty→Event→既有Ledger | 仅Pilot01 |
| L2_REAL_MARKET | 真实行情、币种/单位/日历时间资格 | 未启动 |
| L3_REAL_RESEARCH | 真实研究质量独立验收 | 未启动 |
| L4_REAL_FORWARD | 完整真实Forward预注册与持续运行资格 | 未启动 |

API_BUDGET=0。禁止真实行情、GPT API、Bridge、Broker、交易、Ranking/Price-in修改、Phase11及merge。
新增HOLD_REAL_EVENT_SOURCE_QUALIFICATION；登记HOLD_REAL_A_SHARE_CALENDAR_QUALIFICATION供L2使用。
保留HOLD_MARKET_DATA_PROVIDER_LIVE、HOLD_MODEL_PROVIDER_LIVE、HOLD_REAL_FORWARD_QUALIFICATION及既有校准HOLD。
L1通过不解除L2/L3/L4资格。

## 复用与数据边界

复用Phase2 Source、HTTPAdapter、collect_once、RawObservation、Ledger、OriginClusterVersion、NoveltyDecision、Cursor、SourceHealth、Outbox、commit receipt和publication fence。
L1只添加授权审计、受控来源配置、运行入口与运行报告，不建立第二套事件账本。
Windows目标为Windows11/Python3.12；代码与runtime必须分开。runtime含db/raw/logs/reports/state；原始响应以既有SQLite BLOB为审计权威，不双写第二套原文存储。
禁止真实响应、个人信息、cookie/token/key入Git；报告只提交去敏聚合结果，不转载真实正文。

## 时间与资格

published_at仅为来源声明；first_seen_at是本次响应首次可见；received_at映射既有collected_at（接收完成）。
recorded_at/computed_at/available_at由既有Ledger提交回执和发布fence生成。重试复用原版本first_seen，不能回填历史可知时间。
来源页面更新时间与HTTP Last-Modified不自动等于文章published_at。无法证明则null并记录UNKNOWN。
正式研究仍保留Phase2保守状态，接入成功不是事实可信性/经济逻辑/Forward资格通过。

## 来源授权

每个来源必须登记身份、定位、条款/授权、允许用途、原文保留、访问方法、时间和更新/撤回语义。
UNKNOWN/DENIED/未确认访问限制→HOLD_SOURCE_AUTHORIZATION，禁止事件采集请求。
公开页面不等于无限采集或再分发许可。条款页面只作人工资格核查，不冒充已授权事件流。

## 验收

OFFLINE_CI与LIVE_MANUAL_SMOKE严格分开。CI所有socket连接禁止；真实抓取仅显式live命令、来源授权通过后执行。
L1退出要求三类真实来源持久化完整链路、生命周期/Origin/Cursor/健康/崩溃恢复通过、PIT违规0、无secret入Git及原832项不回归。
未全部满足保持HOLD_REAL_EVENT_SOURCE_QUALIFICATION，不以离线fixture替代真实来源验收。
