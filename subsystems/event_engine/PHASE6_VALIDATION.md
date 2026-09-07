# Phase 6 离线工程验证记录

日期：2026-09-07。接受基线：`36ebcc31e6d0f930833ec27905523cfb0f745b5f`。
工作分支：`build/x-event-engine-phase6`；base=`build/x-event-engine-phase5`。
本报告验证工程契约，不代表真实数据或Alpha验收。

## 最终源码本地原始结果

Windows，复用既有 Python 3.11 隔离环境，PYTHONPATH 指向本分支 `src`。
没有安装/升级依赖。所有 pytest 运行继承禁止真实socket的fixture。

```text
python -m pytest -q tests/test_phase6_graph.py tests/test_phase6_history.py
41 passed in 91.06s (0:01:31)

python -m pytest -q
466 passed in 241.50s (0:04:01)

python -m pytest -q -m pit
141 passed, 325 deselected in 91.09s (0:01:31)
```

保留原Phase1–5的425项测试/126项PIT，本轮新增41项，其中15项PIT。
未修改或删除既有测试；仅新增两个Phase6测试文件。
首轮full为466 passed；最终检查补上Schema原始节点截止门槛后，重新按focused→full→PIT顺序运行，
以上为补齐后的最终结果，不混用修订前结果。

## 覆盖与工程演示

- 铜供应观察与铜价假设分离；生产正向、耗铜负向、综合公司MIXED且原路径完整。
- 空暴露不造路径；SUPPORTED/INFERRED/UNKNOWN/HOLD保级；未实现映射方法仍拒绝。
- 角色错配、叙事缺关联原文、伪造时间、悬空引用、循环/端点/边数错误拒绝或HOLD。
- 深度5保留DEGRADED；新原始节点不可提前；提交后结果不可冒充输入截止时已生成。
- 后来业务修订、本体修订、更名/退市、同源确认、反证不改旧as_of。
- 70转载不产生70倍机制；跨事件合源只改变新计算版本；原历史可回放。
- 原子图事务回滚、重复请求幂等、重复replay一致、只读反查/替代检索。
- JSON Schema、JSON round-trip、各边证据范围及EventVersion未被图层改写。

`python -m xevent.graph.fixture --db <新的隔离库>` 已成功执行。
中文输出：公司净状态MIXED，两条ECONOMIC路径分别POSITIVE/NEGATIVE，
原暴露VERIFIED_DIRECT，经济深度3，结果PLAUSIBLE。
输出声明“这是工程演示，不代表真实Alpha或投资建议。”
`x-event schema --model TransmissionPath` 等价的本地模块入口已导出JSON Schema。

## CI证据位置

独立Event Engine CI继续Ubuntu/Windows × Python3.11/3.12，运行全部466测试、141项PIT与Phase1–6演示。
本地Windows结果不代替其余平台；四组实际run/job结果在本分支Draft PR的检查与验收说明中核对。
以PR当前HEAD关联的实际run为准，不用Phase5基线CI替代本轮结果。

## 隔离、依赖及HOLD

无新依赖，无新SQL表/迁移。requirements锁、DEPENDENCY_MANIFEST、THIRD_PARTY_NOTICES不变。
沿用Python/Pydantic/SQLite Ledger和pytest；不引入Graph框架。
旧schema/引擎业务只增加Ledger和CLI模型注册，不改Market Engine、src/xalpha、Market CI或旧测试。
PR #2 HEAD核对为`425490eb19661fe1becc3b958329d9ccdf01467f`，
Issue #1 updatedAt仍为`2026-09-04T16:13:43Z`；未对它们写入。

持续保留：HOLD_HISTORICAL_UNIVERSE_COVERAGE、HOLD_REAL_COMPANY_EXPOSURE_COVERAGE、
HOLD_PRE_1992_CALENDAR、HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION。
有限虚构产业/公司覆盖，真实经济机制与反路径强度没有实证校准；过期业务连续性、
未知角色、未解析产业、缺关联原文或过期快照均如实保留HOLD/重算原因。
无Live、LLM、价格、排名、交易或Phase7。Issue #11保持OPEN，PR保持Draft，等待人工复审。
