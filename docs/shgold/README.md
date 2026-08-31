# 沪金走势与因子预测原型

> 与美国黄金原型（`../predictor/`）**同一套方法论**的移植版，但因子更贴近沪金的定价恒等式：
> **沪金 ≈ 国际金价 × USD/CNY ÷ 31.1035 + 国内溢价**
> 线上页面：<https://georgezhang-0378.github.io/2026_summer_internship/shgold/>

---

## 一句话结论

用 SHFE 黄金期货主力连续（AU0，Sina 可直接抓取，2008 至今）做目标，叠加人民币、国际金价、国内溢价与全球宏观因子，训练 **walk-forward 随机森林**。

**快照口径**：`as_of = 2026-08-21`，`n_samples = 3417`。**最新沪金 ≈ 987.44 元/克**。

| 窗口 | RF 方向准确率 | 盲赌「总是涨」 |
|---|---|---|
| 21 日 | **73.2%** | 55.1% |
| 63 日 | **81.6%** | 58.3% |

模型在两个窗口都显著赢过盲赌，**是一个可用的方向偏置信号**（幅度点估计仅供参考）。

---

## 数据来源

| 数据 | 来源 | 说明 |
|---|---|---|
| 沪金 AU0 日线 | 新浪 `InnerFuturesNewService.getDailyKLine?symbol=AU0` | 上海期金主力连续，免 key |
| 人民币 USD/CNY | FRED `DEXCHUS` | 沪金关键变量（贬值→沪金涨） |
| 国际金价 | 复用 `../predictor/data/gold_history.csv` | 主驱动 |
| 全球宏观 | FRED `DFII10 / NASDAQCOM / VIXCLS / DTWEXBGS / GVZCLS` | 同美国模型 |

全部免 API key，可直接抓取 → 自动刷新无需任何密钥。

### 沪金专属因子（围绕定价恒等式）

- 沪金自身技术面：`ret_20 / ret_60 / ret_252`、`vol_20 / vol_60`
- `usdcny_chg_20 / usdcny_chg_252`：人民币升贬值
- `intl_ret_20 / intl_ret_60 / intl_ret_252`：国际金价驱动
- `premium_chg_60`：国内溢价变化（均值回复）
- 全球宏观：`real_rate / real_rate_chg_60 / dxy_chg_20 / dxy_chg_252 / vix / vix_chg_20 / gvz / spx_ret_20/60/252`

---

## 模型

与美国模型同参数：**walk-forward 随机森林**，300 棵树 / 深度 6 / 每 21 天滚动重训 / 约 152 个样本外点。分类头给方向 `P(up)`，回归头给收益率（幅度）。

---

## 页面功能

1. **信号卡**：最新 `P(up)`、预测涨跌幅区间（含 ±1σ 置信带）。
2. **历史回放**：选过去日期 → 只用之前数据预测 → 与真实价格画「预测（蓝虚线）vs 实际（金实线）」两条线；超出真实数据后只剩预测线。
3. **因子重要性**：条形图。
4. **回测**：策略净值 vs 买入持有。
5. **上传即分析**：上传自己的 Excel/CSV，做技术面描述（可滚轮缩放区间），不预测。

---

## 如何刷新 / 重生成

```bash
cd docs/shgold
python fetch_shgold.py          # 抓 AU0 + FRED 宏观 + 国际金价 → shgold_factors.csv
python train_shgold.py          # walk-forward RF → signals_shgold.json / backtest_shgold.json
python build_replay_shgold.py   # 历史回放数据 → replay_shgold.json
```

每日自动刷新由根目录 `.github/workflows/refresh.yml` 统一负责（与美国模型同日触发），无需任何密钥。

---

## 文件结构

```
docs/shgold/
├── index.html                  # 页面
├── app.js                      # 前端逻辑（信号卡/回放/因子/回测/上传）
├── fetch_shgold.py             # 数据抓取 + 因子构造
├── train_shgold.py             # walk-forward RF 训练
├── build_replay_shgold.py      # 历史回放数据生成
└── data/
    ├── shgold_factors.csv      # 原始因子时序
    ├── signals_shgold.json     # 最新信号 + 准确率 + 特征重要性
    ├── backtest_shgold.json    # 策略净值
    └── replay_shgold.json      # 历史回放
```

> 局限同美国模型：幅度点估计误差大，方向（P(up)）才是可靠部分；数据快照冻结在 `as_of`，需重跑管线更新。
