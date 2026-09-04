# X — A股 Tail-to-Morning Alpha Research

X 是一个完全独立的新项目。

唯一核心目标：

> 在 T 日尾盘真实可决策时点，对 A 股可交易股票做横截面研究与排序，寻找“尾盘买入后，T+1 早盘更可能出现低风险、可兑现冲高”的候选。

不是泛化预测“明天涨跌”，也不是寻找与历史某天一模一样的 K 线。

## V0.1 核心研究对象

- Next-Morning Return：次日 09:35 / 09:45 / 10:00 收益
- Next-Morning Risk：低开、MAE、早盘下杀风险
- Path：先冲高还是先下杀，例如 `+1% before -1%`
- Cross-Sectional Rank：同一交易日全市场横截面排名

## 技术路线

- 数据：AKShare 等公开接口 + 本地缓存/审计
- 研究框架：Microsoft Qlib
- 首个基线：Alpha158/Alpha360 + LightGBM
- 评估：Walk-Forward + 严格 OOS + Forward Freeze
- RD-Agent：仅在基础 Forward Edge 证明后再接入

## 设计原则

1. Decision Time 之后的数据不得进入特征。
2. 不把次日最高价直接当“可兑现收益”。
3. 不只训练历史入选股票，避免 Selection Bias。
4. 不因模型复杂就默认更优。
5. 可以输出 CASH，不为了给答案而强行选股。
6. 历史数据用于学习结构关系，不用于机械匹配“相同走势”。

当前状态：`X V0.1 Foundation`。
