# Methodology / 方法论

## Prediction target

For each horizon `h`:

```text
future_log_return_h = log(close[t+h] / close[t])
up_h = 1 if future_log_return_h > 0 else 0
```

Primary horizon: 20 trading days.  
主周期：20 个交易日。

Secondary horizons: 5 and 60 trading days.  
辅助周期：5 与 60 个交易日。

## Why both classification and regression?

Direction alone throws away magnitude.  
只判断涨跌会丢失收益幅度信息。

The production model should eventually estimate both:
- `P(up)`
- expected future log return

## Purging

For horizon `h`, labels from the last `h` rows before the test block overlap the future test period and cannot remain in training.  
对于 `h` 日标签，测试区间之前最后 `h` 行的标签会与未来测试期重叠，因此必须从训练集中 Purge。

## Embargo

An additional embargo reduces near-boundary dependence.  
额外 Embargo 用于降低训练与测试边界附近的依赖。

## Scaling

Scaler fits **inside each training fold only**.  
标准化器只能在每个训练 Fold 内拟合。

## Point-in-time

External variables are merged by `available_date`, not merely economic observation date.  
外部变量必须按照 `available_date` 合并，而不能仅按经济数据所属日期合并。

The first version deliberately uses conservative lags.  
第一版故意使用偏保守的滞后规则。

## Metrics

Factor tests report:
- Spearman IC
- AUC
- accuracy
- balanced accuracy
- Brier
- sign consistency
- fold IC

No single metric is allowed to determine admission.  
不得用单一指标决定因子是否通过。
