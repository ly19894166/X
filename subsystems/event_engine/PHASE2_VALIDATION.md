# Phase 2 离线验收记录

日期：2026-09-06。基线：`8134527e0270143ef9827effa776f7b90f372642`，Phase 1 PR #17人工复审通过，Issue #6为COMPLETED。
分支：build/x-event-engine-phase2。只检查指定Issue/PR/HEAD/CI后继续，没有重新全网研究或重做Phase1。

## 本地原始结果

Windows x64 / CPython3.11.9，独立虚拟环境：

```text
python -m pytest -q
........................................................................ [ 48%]
........................................................................ [ 97%]
....                                                                     [100%]
148 passed in 57.60s

python -m pytest -q -m pit
...................................................                      [100%]
51 passed, 97 deselected in 3.51s

python -m pip check
No broken requirements found.

x-event ledger-ingest --db phase2-local-smoke.sqlite --fixture configs/phase2_observations.zh-CN.json
离线持久化完成：原始档案、历史、Novelty和Outbox已提交；接收时间为fixture声明。

Replay versions: 22
```

148=原Phase1的95项+新增53项；PIT51项是总测试子集，不另加到总数。
锁依赖干运行带 `--ignore-installed --require-hashes --no-build-isolation --only-binary=:all: --no-binary=sgmllib3k` 成功，
本平台24个发行依赖完整解析，无缺失传递依赖。独立CI会验证其余三组平台/解释器。

## 核心证据

- 单个Origin→20媒体→50转载归为1个Origin；新转载R1，普通相似但不同文本不合源。
- 同一个输入重试100次仍只有1个逻辑Evidence、1个Event、1个初始Outbox；同键不同内容拒绝。
- raw后、Evidence后、Ledger后、Outbox前、业务commit前/后、回执commit前/后八个故障点均不发布半成品。
- 两项真实子进程os._exit（raw后、业务commit后）验证WAL恢复；不是仅以捕获Python异常冒充进程崩溃。
- 数据库触发器拒绝更新/删除；绕过触发器篡改raw后，读取仍FAIL_CLOSED。
- 原文V1→编辑V2→编辑V3→删除V4，历史字节不抹除；旧as_of和重启前后的Replay完全相等。
- 后来确认同源需另存确认材料、具体引用及可定位原文片段；旧时点独立数量不回填。
- R3/R4/R5后续决定不修改旧决定；R2仅使用完整结构JSON，不允许截取细节掩盖正文变化。
- Source未来版本和HOLD版本不得提前作为正式输入；迟发现旧文章保留真实first_seen/collected。
- recorded_at在业务COMMIT返回后采样；回执commit延迟7秒时available_at也不会提前。
- Outbox消费事务回滚后无幽灵DONE，重试幂等；输入可用时间不能被后续执行倒写。
- Cursor恢复保留原成功/接收时间；响应未保存时不能推进；A→B→A保留三个接收内容版本；304需已有位置。
- UNKNOWN/DENIED授权等七类Gate失败在任何网络请求之前阻止；不能靠内存改Source授权绕过已登记版本。
- HTTP timeout只重试3次；429尊重Retry-After，超过等待预算则HOLD；永久4xx/跳转不重试。
- HTTP/RSS测试均MockTransport，测试进程主动禁止真实socket连接；一个来源失败只记录该来源健康降级。
- 独立CLI可持久化虚构fixture并连续两次Replay得到相同22个版本；没有执行真实网络smoke。

## CI与HOLD

Event Engine独立工作流：Windows/Linux × Python3.11/3.12，锁依赖、pip check、完整148项/PIT51项和两套中文fixture。
实际远端CI结果以本PR Checks及最终PR交付说明为准；本地PASS不代替远端未运行的环境。
未跑第三方框架全套测试，没有重新搜索开源项目，没有调用模型或付费API。

HOLD：真实来源授权/时间语义、历史公开证明、24小时连续运行和硬件断电保证未验收；当前下载能力只可标CURRENT_OBSERVATION_ONLY。
HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION：sgmllib3k1.0.0发行包仅声明BSD License，缺许可证全文/明确条款数；证据已保留，
外部分发/打包前需要补齐核验，不能声称许可全文已齐备或无条件生产发布。
人工确认Origin材料本身的真实性仍须人工核验；字面引用校验不能替代真实性判断。
RSS为响应级原始快照+条目解析输出，不声称已经自动发现每条RSS对应的独立研究事件。

没有修改Market Engine代码/标签/模型/原CI，PR #2 HEAD保持425490eb19661fe1becc3b958329d9ccdf01467f，
Issue #1更新时间保持2026-09-04T16:13:43Z；Phase1工作区干净，PR #17 HEAD未变。
Phase0冻结docs未改。Issue #7保持OPEN，提交独立stacked PR后停止，等待人工复审，不进入Phase3。
