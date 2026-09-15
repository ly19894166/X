# L1 REAL EVENT — Pilot 01

状态：HOLD_REAL_EVENT_SOURCE_QUALIFICATION（资格审核与实现中）。
分支：codex/x-real-landing-l1-pilot01；base为Phase10接受HEAD。

候选来源仅三类：A 上海/深圳交易所正式披露；B 中国政府或监管正式政策发布；C 海外监管机构正式披露。
最终locator、条款核查依据和实际接入结果必须在来源注册表及验收报告逐项列明。未知项不能默认为许可。

## Pilot契约

1. 先审来源条款和技术限制；通过前Source禁用，HOLD_SOURCE_AUTHORIZATION。
2. 一次人工触发、有界请求，不运行daemon，不追踪条目链接、不绕过403/验证码/登录/robots或跳转。
3. 采用固定且可解释的响应观察event seed；页面/Feed响应级观察不冒充自动发现每条独立事件。
4. 复用Phase2 append-only版本：NEW→INITIAL、UPDATED/CORRECTED→EDIT、明确撤回→RETRACT、明确删除→DELETE。
5. HTTP404或Feed条目消失只视为SOURCE_UNAVAILABLE，不能自动证明撤回；撤回需要来源明示材料。
6. EXACT_DUPLICATE复用旧Evidence/Event，追加既有R0审计；A→B→A保存三版。
7. 普通文本Novelty采用UNDETERMINED/HOLD，禁止猜测R2–R5；完整结构化来源证明才应用旧规则。
8. 同源转载、直接引用、未知Origin及真正独立来源按Phase2保守规则验收，不用文本相似度声称独立确认。
9. timeout/429/5xx/4xx/redirect/Retry-After/断网/解析异常/内容异常只影响对应SourceHealth。
10. 响应提交后Cursor失败可恢复，重启依据Ledger固定历史，不依赖内存状态。

## 测试与运行证据

新增离线测试覆盖授权Gate、全部生命周期、时间顺序、哈希、Origin/Novelty、失败隔离、Cursor与崩溃恢复。
真实源只做最小LIVE_MANUAL_SMOKE；真实站点不可控的更新/撤回采用离线故障注入单独验证，绝不将模拟变更称为真实撤回。
focused→full→PIT→Windows/Linux四环境CI；原832项不修改。
Windows11/Python3.12本地部署与live原始数据均在Git工作树之外，未验收明确HOLD。

最终只在三类真实来源和所有退出条件均满足时标REAL_EVENT_PILOT_QUALIFIED；否则列出逐源阻塞并保持HOLD。
完成后停止，不启动L2。

## 来源审核记录（2026-09-15）

正式注册表：pilot01_sources.json。只登记三类正式Pilot来源；SEC仅作为资格调查失败的候选，403后未绕过或接入。

- A：上海证券交易所，一条固定交易所正式公告。法律声明第三项明确允许非商业浏览、下载；本Pilot仅本地非商业研究，不转售、不转载原文、不抓行情、不跟随链接。登记AUTHORIZED仅代表此有限用途，不是无限使用许可。
- B：中国政府网政策栏目。网站声明禁止擅自转载其他单位提供的信息，并限制商业原版转载；当前未取得足以确认自动采集和原文留存的明确依据。登记UNKNOWN，保留HOLD_SOURCE_AUTHORIZATION，事件采集请求必须为0。
- C：美联储官方Banking and Consumer Regulatory Policy RSS。官方feeds说明允许reader/aggregator订阅；版权说明明确其自有信息原则上public domain，可复制且要求注明来源。仅下载feed文字响应，不取第三方图像、附件、商标或条目链接。登记NOT_REQUIRED仅适用于已审核范围。

SSE/FRB的robots.txt在审核时返回404；这不被用作授权依据。授权来自上述正式条款，访问限制来自有界、人工触发、无跳转的现有HTTPAdapter。SEC 403保持不可访问，不换代理/身份绕过。

每条来源审核保存审核时点、条款定位、SHA-256、短原文依据、operator、用途与生命周期语义。实时原文仅在runtime SQLite存储。
SSE日期仅精确到日、RSS为多条目响应：published_at保留UNKNOWN/null；first_seen/received/available使用本地真实时钟和提交回执。
本轮接入的Event为固定来源定位响应观察，不声称逐条自动事件发现，不生成经济事实。

## Windows本地运行骨架

目标Windows11/Python3.12。接受HEAD以git archive独立部署到runtime/code/accepted-phase10，固定既有代码。
L1以独立namespace overlay加载，启动器核对当前Python为3.12及Phase10模块路径，拒绝误加载其他checkout。
实际runtime选用用户目录下XRealLanding/pilot01短路径，避免AppData重定向造成跨盘rename和Windows路径长度错误。
初次AppData安装失败属于本地环境失败，未取得事件数据，不影响任何Ledger；保留失败记录，不修改系统长路径策略。

在已安装锁定依赖与接受包的runtime venv中执行：

```powershell
$runtime = Join-Path $env:USERPROFILE 'XRealLanding/pilot01'
$python = Join-Path $runtime 'venv/Scripts/python.exe'
# 从本L1工作树运行；不要设置指向其他checkout的PYTHONPATH
& $python scripts/real_landing/run_l1.py smoke --runtime $runtime --registry docs/real_landing/pilot01_sources.json --live-manual-smoke
& $python scripts/real_landing/run_l1.py audit --runtime $runtime --registry docs/real_landing/pilot01_sources.json
& $python scripts/real_landing/run_l1.py recover --runtime $runtime --registry docs/real_landing/pilot01_sources.json
```

smoke每源最多1次HTTP请求；需重复时显式再次运行。UNKNOWN授权源登记AUTHORIZATION_HOLD但不发请求。
原始数据权威在db/events.sqlite；raw目录预留，不双写原文。reports为去正文审计，state保存审核注册表快照；logs预留手工命令日志。
不启动daemon，不消费Outbox进入下一阶段。运行报告默认HOLD，必须结合人工来源资格与离线验收证据才可决定L1退出。

## LIVE_MANUAL_SMOKE实际验收（2026-09-15 UTC）

Windows11 10.0.26200 / Python3.12.10；锁定依赖安装和pip check通过。136个接受文件规范化后与Git blob一致（135个仅CRLF转换），没有业务语义修改。
首次采集2026-09-15T03:17:54Z至03:17:56Z，重启后第二次人工采集约03:18:39Z。

| 来源 | Raw | Evidence | Origin | Event版本 | Novelty | SourceHealth | Cursor |
|---|---:|---:|---:|---:|---|---|---|
| SSE_PILOT01 | 1 | 1 | 1 | 1 | UNDETERMINED=1, R0=1 | OK | v2 |
| GOVCN_PILOT01 | 0 | 0 | 0 | 0 | 无 | AUTHORIZATION_HOLD | v2，无成功位置 |
| FRB_PILOT01 | 1 | 1 | 1 | 1 | UNDETERMINED=1 | OK | v2 |

SourceHealth和Cursor也采用既有append-only记录。授权HOLD的Cursor只记录失败尝试，不代表成功采集。
两次采集没有新增独立Event；SSE精确重复产生R0。FRB保留首次原文与首次接收时间，不凭Cursor推进推断有新信息。

SSE first_seen=03:17:54.955920Z，received=03:17:54.960698Z，recorded=03:17:54.977351Z，available=03:17:54.998199Z。
FRB first_seen=received=03:17:56.295976Z，recorded=03:17:56.348652Z，available=03:17:56.366284Z。
published_at均为null/UNKNOWN，未用历史页面日期或HTTP缓存头回填系统可知时间。

在03:17:54Z旧cutoff三源Raw/Event均为0；03:17:57Z旧cutoff仍只看到两条已提交事件。重启和显式recover后原版本保持。
实际审计PIT violation=0，原始字节SHA-256经过Ledger校验。原始响应、真实库、完整时间审计与部署清单只在仓库外runtime。

真实站点更新/撤回没有在两次短smoke期间发生；只报告离线NEW/重复/A→B→A/更正/撤回/删除/失败注入通过，不冒充真实撤回。
SOURCE_UNAVAILABLE、timeout/429/5xx/4xx/redirect/Retry-After/解析/内容异常/断网/Cursor失败/进程崩溃由新增测试与复用Phase2测试覆盖。

## OFFLINE_CI / 本地测试（交付提交时快照）

- 新增L1：36项；原832项保持不变。
- 最终focused（L1+Phase2复用）：`99 passed in 64.21s (0:01:04)`。
- full：运行中。
- PIT：等待full成功后运行。
- 四环境CI：待提交后运行；CI没有LIVE_MANUAL_SMOKE步骤，socket继续由既有autouse fixture禁止。
- 最终full/PIT及exact-head四环境CI原始结果在关联Draft PR和Issue #27记录，以避免为更新CI状态再改变已测HEAD。

当前结论：HOLD_REAL_EVENT_SOURCE_QUALIFICATION。原因是B类来源自动采集/原文留存授权尚未明确，未满足三类真实来源退出条件。
L2/L3/L4、真实A股日历、行情Provider、模型Provider、真实Forward和既有策略校准HOLD均继续保留。
Issue #27保持OPEN，交付使用Draft PR，不merge、不启动L2、不进入Phase11。
