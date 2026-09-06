# Phase 4：影响变量、X产业本体与独立叙事主题

输入：Issue #9、2026-09-07用户Phase4指令及冻结总体规范V0.1。
接受基线：`build/x-event-engine-phase3` / `8469ea722e65cc0f6975b3be0ed88b5fb5d9767d`。
独立stacked Draft PR以该分支为base；不合并或修改PR #19。只输出事件影响和产业候选。

## 范围和数据流

```text
固定EventVersion + 固定EvidenceVersion + 显式原文核验
  → ImpactVariable OBSERVED
固定Evidence/Impact前提 + 中文机制 + 不确定性
  → ImpactVariable HYPOTHESIS
ImpactVariable + 固定OntologyVersion + as_of
  → IndustryResolution → IndustryImpactCandidate（可同时正向/负向）

固定EventVersion + 主题证据 → NarrativeTheme（经济路径UNRESOLVED）
```

Phase4只读取Event/Evidence。没有EventVersion、三维状态、时钟、重算队列的反向写入。
不包含Company、Security、Transmission Graph、价格行情、Price-in、排名或交易。

## 标准影响变量

`ontology/contracts.py`声明有限词表；Pydantic拒绝未知内部值。正式表达只有`variable_type + direction`。
类型为DEMAND、SUPPLY、PRICE、INPUT_COST、ORDER、CAPEX、MARKET_SHARE、IMPORT_SUBSTITUTION、
EXPORT_OPPORTUNITY、SUBSIDY、REGULATORY_PRESSURE、FINANCING_COST、FX、RISK_PREMIUM。
方向为UP/DOWN/FLAT/UNKNOWN。按本轮明确指令，Phase4价格变量统一为`PRICE`；冻结文档中的旧称
`OUTPUT_PRICE`不作为第二种存储枚举，不改写Phase0文件。观察字段统一为`observation_kind`，不再保存同义的inference_type。

`normalize_impact_phrase`是显式输入短语表：DEMAND_INCREASE、STRONGER_DEMAND、DEMAND_RISING、需求增长
都只转换成DEMAND+UP；这些短语直接写入正式枚举会拒绝。未知短语返回None，不能自动造词或猜测。

初始target_object注册为COPPER/ELECTRICITY/AI_COMPUTE/MANUFACTURING/CURRENCY；地理范围为
GLOBAL/CN/US/EU/JP/UNKNOWN。它们是有限的工程词表，不代表全球经济对象覆盖；新增目标需显式词表/策略修订。
unit和currency使用有限枚举，未知单位为UNKNOWN，没有用0补缺失数值；本Phase不估计影响幅度。
有吨价单位时币种必须一致。FX必须给出base/quote、明确direction、CURRENCY、FX_RATE以及等于quote的currency。
USD/CNY UP表示每美元兑换人民币增加。FX规则也必须带相同币种对，CNY/USD UP不会匹配USD/CNY UP。

`confidence`是UNKNOWN或离散研究判断Band，不是校准概率。`validation_status`记录UNREVIEWED/VERIFIED/HOLD。
继承信封的`status`表示记录是否可发布；它不等于经济判断已通过。可发布的HOLD研究记录保留领域HOLD状态，方便审计和后续复核。

## OBSERVED与HYPOTHESIS边界

OBSERVED必须有ObservationBasis：固定原始Evidence、原文片段、核验人、中文解释、观察范围。
范围区分ANNOUNCED_CHANGE（宣布）、REPORTED_CHANGE（报告）、MEASURED_CHANGE（测量）。
服务检查材料确属指定EventVersion、claim_kind=FACT、quality_status=VALIDATED，且片段存在于不可变原文。
这记录了人的明确语义核验，不声称自动理解原文或保证来源真实性；宣布减产也不等于减产已经执行。

HYPOTHESIS必须有固定Evidence/Impact premise_refs、mechanism_zh和uncertainty_zh；不能带ObservationBasis，
不能标validation_status=VERIFIED。OBSERVED不能以派生premise替代原文核验。跨事件/缺失/未来版本拒绝。
例如供应减少是SUPPLY/DOWN/OBSERVED，而可能引起铜价上涨是另一个PRICE/UP/HYPOTHESIS对象。
后者不能从前者自动变成已观察铜价事实。

仅NarrativeTheme不能传入影响解析器；若假设前提全部是NARRATIVE证据，经济解析也保持UNRESOLVED。
含经济主张的传闻/预测/意图可以作为待研究假设前提，但不能变成OBSERVED；这样保留合理风险候选，不把未核验输入全量丢弃。
前提链的HOLD向下游候选传播，原始证据沿链保留。缺价格观察不会生成NO_REACTION或任何Price-in判断。

## 本体和版本发布

| 对象 | 机器职责 |
|---|---|
| IndustrySegment | XIND_稳定ID、中文名、固定父引用/parent_id、level、经济角色、描述、aliases、有效区间、本体版本 |
| IndustryAlias | 独立alias ID、精确短语、固定industry_ref及可选Evidence；不模糊搜索 |
| ExternalCrosswalk | 外部系统/代码/名称、X产业、映射类别/状态、provenance和核验依据 |
| IndustryImpactRule | 精确影响类型/目标/方向/地区/FX pair → 固定产业，正负方向、path_role、机制和证据 |
| OntologyVersion | 一次发布的不可变manifest；固定引用全部segment/alias/crosswalk/rule版本 |
| ImpactVariable | 事件影响，OBSERVED/HYPOTHESIS隔离；固定原文/前提引用 |
| NarrativeTheme | 独立主题实体；没有industry_ref，经济路径固定UNRESOLVED |
| IndustryImpactCandidate | 影响/本体/规则/产业固定引用、正负方向、机制、证据、领域状态和不确定性 |
| IndustryResolution | 某次固定输入/as_of对应的候选集合 |

`OntologyDraft`是发布输入，验证非空树、ID唯一、无循环、无悬空parent、level与父关系、有效期。
alias/crosswalk/rule目标必须存在。服务固定字典类型，NarrativeTheme不能被用作IndustrySegment。

`publish`按完整快照发布，manifest版本必须连续；重复同版本同输入幂等，不同输入冲突。
各成员有自己的连续对象版本，新节点从v1开始；后续同ID只追加，不覆写。旧产业ID必须保留，
不能用同ID改变经济角色；退役使用effective_to。中文名称和描述的语义是否仍属于同一身份需人工审核，机器不做语义身份核验。
alias同ID不能更换规范短语，crosswalk同ID不能换外部系统/Provider/代码。新版本可显式撤下别名或规则，旧manifest仍可回放。

解析只读指定manifest，绝不从动态latest成员补齐。`resolve_alias`可显式提供ontology_ref；省略时选择
as_of当时已知的最高manifest版本，并在返回值中记录该固定引用。精确规范化仅含Unicode NFKC、空白、大小写。
零匹配或多个产业匹配都返回UNRESOLVED。产业尚未生效/已到effective_to也不匹配。

ExternalCrosswalk只预留SHENWAN/CITIC/GICS/GB_T_4754/EXCHANGE/PROVIDER。Provider/交易所必须写名称。
外部代码保存字符串（fixture的000001保留前导零，不是证券代码）。未知映射必须UNRESOLVED、产业引用null；不作模糊猜测。
VERIFIED crosswalk/规则需已校验FACT证据、核验人和中文provenance/机制。fixture映射默认CANDIDATE，不声称真实外部分类对应关系。
代码许可证与外部分类/数据使用条款分离；本Phase未导入真实外部分类或取得其使用授权。

## 产业候选规则

`resolve(impact_ref, ontology_ref, as_of, request_key)`只按精确类型/目标/方向/地区及币种对选择规则。
规则地区GLOBAL表示该机制适用各已知地区，不代表证据是全球覆盖；影响地区UNKNOWN不能被当成GLOBAL。
产出保留PRODUCER/INPUT_USER等path_role与POSITIVE/NEGATIVE/NEUTRAL/UNCERTAIN方向。
铜价上涨fixture同时输出铜矿生产POSITIVE和高耗铜制造NEGATIVE；不只保留“受益者”。

无规则/未知地区方向/仅主题前提/目标行业不在有效期时，输出一条industry_ref=null的UNRESOLVED记录。
机制有明确规则且未HOLD时输出CANDIDATE；任一前提Impact或规则HOLD则输出HOLD。
**候选一律是HYPOTHESIS，不由规则的VERIFIED升级为已验证经济效果。**候选证据为影响前提链及对应规则的具体证据。
没有合格映射不影响原始Evidence留存，也不停止其他事件。

同一Impact固定版本、Ontology固定版本、as_of、策略版本得到相同排序的业务候选；
相同request_key完全幂等。不同request_key的审计ID/提交时间可不同，业务字段确定性一致。
产业影响还依赖库存、合约、需求、成本转嫁等条件；这里只记录候选机制，不计算公司利润或任何股票影响。

## 事务与PIT

复用Phase2五表SQLite Ledger、WAL、append-only触发器、业务提交后回执和publication fence。
仅在Ledger模型注册表增加9种Phase4记录；不重构Phase1–3，无DB schema迁移或新依赖。
本体成员与manifest同事务；候选与resolution同事务。回滚无半份树/候选，提交后崩溃沿已有回执协议恢复。
recorded_at继续代表耐久化业务提交完成；available_at覆盖输入、计算及提交/发布门槛。

任何本体/alias/crosswalk/impact/规则只有available_at<=as_of才能被读取；effective_from较早不改变可知时间。
未来明确版本不能用于过去查询；历史as_of只读当时manifest，新增alias/映射/本体不会反填过去。
10:00无“上游铜资源”alias→UNRESOLVED；11:00发布新增alias；10:30回放仍UNRESOLVED，11:30才MATCHED。

## 离线CLI与HOLD

```text
x-event ontology-fixture --db phase4-demo.sqlite --fixture configs/phase4_ontology.zh-CN.json
x-event schema --model ImpactVariable
python -m pytest -q tests/test_phase4_ontology.py
python -m pytest -q
python -m pytest -q -m pit
```

演示只允许新隔离库，输出中文观察/推断、正负候选、独立主题、晚到alias的前后结果和Event未修改断言。
所有测试禁止真实socket；四组独立CI继续Phase1–3回归，并增加Phase4中文fixture。

HOLD：本体仅3个虚构节点/2条规则，不是全产业覆盖；目标词表有限；语义核验、真实外部分类授权、
经济机制有效性/置信度校准、真实数据覆盖均未验收。未知分类或模糊主题保持UNRESOLVED。
无新依赖，已有依赖/锁/许可证不变；保留sgmllib3k `HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION`。
未联网采集、未调用LLM/付费API、未做Live。Market Engine、src/xalpha、PR #2不修改。
Issue #9保持OPEN，等待人工复审；执行到此停止，不进入Phase5。
