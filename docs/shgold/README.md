# 沪金走势与因子预测原型

> 与美国黄金原型（`../predictor/`）**同一套方法论**的移植版，但因子更贴近沪金的定价恒等式：
> **沪金 ≈ 国际金价 × USD/CNY ÷ 31.1035 + 国内溢价**
> 线上页面：<https://georgezhang-0378.github.io/2026_summer_internship/shgold/>

---

## 一句话结论

用 SHFE 黄金期货主力连续（AU0，Sina 可直接抓取，2008 至今）做目标，叠加人民币、国际金价、国内溢价与全球宏观因子，训练 **walk-forward 随机森林**。

**快照口径**：`as_of = 2026-09-01`，`n_samples = 4014`。**最新沪金 ≈ 959.94 元/克**。

| 窗口 | RF 方向准确率 | 盲赌「总是涨」 |
|---|---|---|
| 21 日 | **73.2%** | 55.1% |
| 63 日 | **81.6%** | 58.3% |

模型在两个窗口都显著赢过盲赌，**是一个可用的方向偏置信号**（幅度点估计仅供参考）。

---

## 数据来源

| 数据 | 来源 | 说明 |
|---|---|---|
| 沪金 AU0 日线 | 新浪 `InnerFuturesNewService.getDailyKLine?symbol=AU0` | 上海期金主力连续，免 key；**若抓取失败则用恒等式推导补齐最新交易日**：`沪金 ≈ 国际金价 × USDCNY ÷ 31.1035 + 上一已知溢价` |
| 人民币 USD/CNY | **免 key 兜底链**：Yahoo `USDCNY=X` → Stooq → FRED `DEXCHUS` | 沪金关键变量（贬值→沪金涨） |
| 国际金价 | 复用 `../predictor/data/gold_history.csv`，缺失时 `TD_KEY`→Yahoo→Stooq 兜底 | 主驱动 |
| 美元指数 | **免 key 兜底链**：Yahoo `DX-Y.NYB` → Stooq → FRED `DTWEXBGS` | 沪金关键变量 |
| 全球宏观 | FRED `DFII10 / NASDAQCOM / VIXCLS / GVZCLS` | 同美国模型 |

全部免 API key：Sina 与 FRED 长期免 key，USD/CNY 与美元指数在 CI 中经 Yahoo/Stooq 兜底链直连 → **自动刷新无需任何密钥**（`TD_KEY` 仅作为可选升级，用于国际金价兜底）。`fetch_shgold.py` 还会把新数据按日期 `combine_first` 合并回 `shgold_factors.csv`，保留完整历史。

### 沪金专属因子（围绕定价恒等式）

- 沪金自身技术面：`ret_20 / ret_60 / ret_252`、`vol_20 / vol_60`
- `usdcny_chg_20 / usdcny_chg_252`：人民币升贬值
- `intl_ret_20 / intl_ret_60 / intl_ret_252`：国际金价驱动
- `premium_chg_60`：国内溢价变化（均值回复）
- 全球宏观：`real_rate / real_rate_chg_60 / dxy_chg_20 / dxy_chg_252 / vix / vix_chg_20 / gvz / spx_ret_20/60/252`

#### 因子公式（动量为例）

记 `s_t` 为第 t 个交易日的沪金收盘价，`r_t = s_t / s_{t-1} − 1`。`train_shgold.build_features` 中的核心实现（沪金动量用「N 个日收益相加」，小波动下等价于 `s_t/s_{t-N} − 1`）：

```python
r = shgold.pct_change()                     # 日收益率
shgold_ret_20 = r.rolling(20).sum()         # ≈ g_t / g_{t-20} − 1   ← 20日动量
shgold_vol_20 = r.rolling(20).std() * sqrt(252)   # 20日年化波动率
intl_ret_20   = intl_gold.pct_change().rolling(20).sum()  # 国际金价动量（主驱动）
usdcny_chg_20 = usdcny.pct_change(20)       # 人民币 20 日变化
premium_chg_60= premium.pct_change(60)      # 国内溢价 60 日变化（均值回复）
```

**标签（未来 h 日收益符号，无前视泄漏）**：

```python
target_21 = s.pct_change(21).shift(-21)     # = s_{t+21} / s_t − 1
dir_21    = (target_21 > 0)                 # 1=涨, 0=跌
# 63 日窗口同理用 shift(-63)
```

> 与美国模型差异：沪金动量写成「滚动 N 日收益求和」而非「价格比减 1」，二者在日波动较小时几乎等价；因子选择围绕定价恒等式「沪金 ≈ 国际金价 × USD/CNY + 国内溢价」展开，因此比美国模型多了 `usdcny_chg`、`intl_ret`、`premium_chg` 这几组汇率/国际金价/溢价因子。

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

### 线是「提前算好上传」还是「当场画」？

与（美国黄金）完全一致的「**预计算端点 + 实时绘制**」模式：

- Python 离线算出 `signals_shgold.json / replay_shgold.json / backtest_shgold.json` 并 `git push`；网页打开时纯前端 `fetch(..., {cache:'no-store'})` 读取后交给 ECharts 绘制（`cache:'no-store'` 只绕浏览器缓存，**不联网拉新数据**）。
- **回放「预测 vs 实际」两条线**：实际线 = `replay_shgold.json` 的 `gold`（历史价）+ 各锚点的 `future`（真实后续价）拼接而成的金实线；预测线 = 每个回放点只存的两个端点（预测日价 `startP` 与 `startP×(1+pred_ret/100)`）之间画的蓝色虚直线。超出真实数据后只剩预测虚线，信息栏会提示真实金价截至日。

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
