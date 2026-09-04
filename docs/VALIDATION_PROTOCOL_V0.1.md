# X Validation Protocol V0.1

## 最终裁判

回测只用于研究；Forward Test 才是升级依据。

## 数据切分

只允许时间顺序：Train -> Validation -> Locked Test。

禁止随机打乱整个时间序列后切分。

## Walk Forward

每个测试窗口只能使用其之前的数据训练。测试窗口结果不得反向参与当次模型选择。

## 核心指标

Ranking：Daily RankIC、Top5/10/20 相对 Universe Edge。

Return：09:35 / 09:45 / 10:00 平均值、中位数、分位数。

Risk：MAE、低开率、先 -1% 比率、峰谷回撤。

Path：`P(+1 before -1)` 的校准度和 Brier/LogLoss。

Stability：年份、市场状态、行业、流动性分组、Alpha Decay。

## Forward Freeze

T 日尾盘必须先冻结：

- model_version
- data_version
- feature_schema
- decision_ts
- 全 Universe prediction/rank

T+1 10:05 后只允许结算，不允许重算 T 日预测覆盖原记录。

## 禁止伪优势

- 不把涨停买不到的票按可成交计算
- 不把次日最高点当稳定卖点
- 不用测试集反复调参
- 不删除失败样本
- 不以少数极端收益替代整体稳定性
