# X Strategy Spec V0.1

## 1. Frozen objective

交易路径固定为：

`T 日尾盘买入 -> 隔夜持有 -> T+1 早盘寻找冲高卖出`

系统不以 `T+1 Close Return` 作为唯一或主要优化目标。

## 2. Decision Time

研究窗口：14:30—14:55。

V0.1 建议主快照：14:50；允许额外保存 14:35 / 14:45 用于比较，但任何样本必须保存自己的 `decision_ts`。

铁律：某个样本的任何 feature 必须满足 `feature_available_at <= decision_ts`。

不得用 15:00 后才确定的信息回填 14:50 特征。

## 3. T+1 outcome window

主结果窗口：09:31—10:00。

必须同时保留：

- 09:35 / 09:45 / 10:00 固定时点收益
- MFE（理论最大有利波动）
- MAE（相对 entry 的最大不利波动）
- 首次触达 +0.5 / +1.0 / +1.5
- 首次触达 -0.5 / -1.0
- `+1% before -1%` 路径
- MFE / MAE 时间

## 4. Realizable Edge

不得把 MFE 当实盘收益。

V0.1 先训练原子目标：固定时点收益、MFE、MAE、路径概率和横截面排名。`Realizable Return` 的正式公式必须通过严格 OOS + Forward Test 后再冻结。

## 5. Model heads

- Return：预测 09:35 / 09:45 / 10:00 收益
- Risk：预测 MAE、低开、严重下杀
- Path：预测 `P(+1 before -1)`、触达概率
- Rank：同日股票横截面 Morning Alpha Rank

首个基线优先 LightGBM；复杂深度模型必须以 OOS 稳定提升为进入条件。
