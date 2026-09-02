# 美国黄金方向预测原型 · 完整工作逻辑

> 本文件把 `docs/predictor/` 下整条管线讲清楚：数据从哪来、做了哪些特征、模型怎么训练、产出什么、以及**它到底准不准**。
> 模型快照口径：`as_of = 2026-08-31`，`n_samples = 3751`。
> 线上页面：<https://georgezhang-0378.github.io/2026_summer_internship/predictor/>

---

## 0. 一句话结论

这是一个 **walk-forward（滚动重训）随机森林**，吃「5 个 FRED 宏观因子 + 金价技术面」，预测未来 **21 日 / 63 日** 金价是涨是跌（方向）以及涨跌幅（收益率点估计）。

**诚实对照**：RF 方向准确率 **21日 72.1% / 63日 79.6%**，而「无脑赌涨」只有 **53.6% / 56.9%**，WGC 朴素因子规则 **48.9%**。模型在 21/63 两个窗口上都显著赢过基准，所以它是一个**可用的方向偏置信号**，不是噪声。

---

## 1. 整体流水线

```mermaid
flowchart LR
    A[FRED 免key CSV<br/>实际利率/纳指/VIX/美元/GVZ] --> E
    B[金价历史<br/>Twelvedata TD_KEY<br/>或本地 gold_history.csv] --> E
    C[WGC 央行净购金<br/>cb_gold.csv] --> E
    E[fetch_factors.py<br/>拼接+对齐] --> F[factors.csv]
    F --> G[train_rf.py<br/>walk-forward RF]
    G --> H[signals.json<br/>最新信号+准确率+特征重要性]
    G --> I[backtest.json<br/>策略净值]
    G --> J[build_replay.py]
    F --> J
    J --> K[replay.json<br/>历史回放(预测vs实际)]
    H --> L[站点渲染<br/>信号卡/回放/因子/回测/上传自分析]
    I --> L
    K --> L
```

重跑方式（本地一键）：`cd docs/predictor && python run.py`（会依次调用 `fetch_factors.py` → `train_rf.py`）。
每日自动重跑由 `.github/workflows/refresh.yml` 负责（见第 7 节）。

---

## 2. 数据来源

| 数据 | 变量 | 来源 | 说明 |
|---|---|---|---|
| 实际利率 | `real_rate` | FRED `DFII10`（10Y TIPS 收益率） | 持有黄金的机会成本，最关键宏观变量 |
| 美股 | `spx` | FRED `NASDAQCOM` | FRED 的 SP500 日线只从 2016 起，改用纳指综合（2008 起）代理，历史更长且高度相关 |
| 波动率 | `vix` | FRED `VIXCLS` | 避险/恐慌温度计 |
| 美元 | `dxy` | FRED `DTWEXBGS` | 贸易加权美元指数（广义） |
| 黄金波动 | `gvz` | FRED `GVZCLS` | CBOE 黄金隐含波动率 |
| 金价（目标） | `gold` | **免 key 兜底链**：`TD_KEY`→Yahoo `GC=F`→Stooq `xauusd`→本地 `gold_history.csv` | **回归目标**：未来 21/63 日收益符号 |
| 央行购金 | `cb_net` | WGC 年报整理的 `cb_gold.csv` | 年度净购金吨数，结构性利好 |

> FRED 走 `fredgraph.csv` 免 API key 直接拉。金价抓取（`fetch_gold()`）为**免 key 兜底链**：配置了仓库密钥 `TD_KEY` 则优先走 Twelvedata `XAU/USD`；否则依次尝试 **Yahoo `GC=F`**、**Stooq `xauusd`**；都失败才读本地 `gold_history.csv`。抓到的新价用 `combine_first` **按日期合并回 `gold_history.csv`，只追加新交易日、不截断 2011 年起的历史**。GitHub Actions 服务器能直连 Yahoo/Stooq，因此**无需任何密钥即可每日自动更新到最新交易日**；`TD_KEY` 只是把 Twelvedata 升为第一优先源（更稳，免受限频/数据中心 IP 封锁）。

---

## 3. 特征工程

标签：`dir_h`（未来 h 日金价收益符号，`shift(-h)`，保证无前视泄漏）。

共 **15 个特征**，分两组：

**A. 金价技术面（5 个）**

| 特征 | 窗口 | 含义 |
|---|---|---|
| `gold_ret_20` | 20 日 | 短期动量 |
| `gold_ret_60` | 60 日 | 中期动量 |
| `gold_ret_252` | 252 日 | 年化动量（1 年） |
| `gold_vol_20` | 20 日 | 短期波动率 |
| `gold_vol_60` | 60 日 | 中期波动率 |

**B. 宏观/市场面（10 个）**

| 特征 | 窗口 | 含义 |
|---|---|---|
| `real_rate` | — | 实际利率水平 |
| `real_rate_chg_60` | 60 日 | 实际利率变化 |
| `dxy_chg_20` | 20 日 | 美元短期变化 |
| `dxy_chg_252` | 252 日 | 美元 1 年趋势 |
| `vix` | — | 波动率水平 |
| `vix_chg_20` | 20 日 | VIX 变化 |
| `gvz` | — | 黄金隐含波动率 |
| `spx_ret_20` | 20 日 | 美股短期收益 |
| `spx_ret_60` | 60 日 | 美股中期收益 |
| `spx_ret_252` | 252 日 | 美股 1 年收益 |
| `cb_net` | — | 央行年净购金 |

`feasible_features()` 会根据当前可用历史长度动态挑选特征（样本不够 252 日时自动去掉长窗口特征），避免早期样本全为 NaN。

### 3.1 因子公式（以动量为代表）

记 `g_t` 为第 t 个交易日的收盘价，日收益率 `r_t = g_t / g_{t-1} − 1`。`fetch_factors.build_features` 里的核心实现：

```python
# 金价技术面（动量 = 价格比减 1；波动率 = 年化标准差）
gold_ret_20  = g.pct_change(20)            # = g_t / g_{t-20} − 1      ← 20日动量
gold_ret_60  = g.pct_change(60)            # = g_t / g_{t-60} − 1      ← 60日动量
gold_ret_252 = g.pct_change(252)           # = g_t / g_{t-252} − 1     ← 年化动量
gold_vol_20  = r.rolling(20).std() * sqrt(252)   # 20日年化波动率
gold_vol_60  = r.rolling(60).std() * sqrt(252)   # 60日年化波动率

# 宏观/市场面（多为水平值或「变化」）
real_rate       = DFII10                      # 10Y TIPS 实际利率（水平）
real_rate_chg_60= real_rate.diff(60)          # 实际利率 60 日变化
dxy_chg_20      = dxy.pct_change(20)          # 美元 20 日变化率
dxy_chg_252     = dxy.pct_change(252)         # 美元 1 年趋势
vix_chg_20      = vix.diff(20)                # VIX 20 日变化
spx_ret_20      = spx.pct_change(20)          # 美股 20 日动量
```

**标签（未来 h 日收益符号，无前视泄漏）**：

```python
target_21 = g.shift(-21) / g - 1      # = g_{t+21} / g_t − 1
dir_21    = (target_21 > 0)           # 1=涨, 0=跌
# 63 日窗口同理用 shift(-63)
```

> 要点：动量因子就是「过去 N 日价格变化率」，`pct_change(N)` 等价于 `g_t / g_{t-N} − 1`；波动率用滚动标准差年化（`×√252`）。所有特征只用到「截至当天」的数据，标签用 `shift(-h)` 看未来，因此训练集不存在前视泄漏。

---

## 4. 模型：walk-forward 随机森林

不是「全样本一次性训练」——那样会前视泄漏。采用 **滚动窗口**：

- 起始训练集：`min(500, max(120, n//3))` ≈ **500 个交易日**。
- 从第 500 天起，**每隔 21 天**用「截至当天 all 历史」重训一棵树，预测「下一天」的方向，再往后推 21 天重复。
- 这样得到约 **152 个**真正样本外（out-of-sample）预测点，用于算准确率。

随机森林参数（与主模型一致，强而稳）：

```python
RandomForestClassifier(
    n_estimators=300,   # 300 棵树
    max_depth=6,        # 限制深度，防过拟合
    min_samples_leaf=20,
    random_state=42,
    n_jobs=-1
)
```

- 分类头：预测方向（涨/跌）+ 涨的概率 `P(up)`。
- 回归头（`RandomForestRegressor`，同参数）：预测未来收益率（幅度点估计，误差较大，**仅供参考**）。

---

## 5. 输出文件（站点直接读取的静态 JSON）

| 文件 | 内容 |
|---|---|
| `data/signals.json` | 最新日期信号、`P(up)`、`pred_ret_*`、整体方向准确率、特征重要性、样本量 `n_samples`、快照日 `as_of` |
| `data/replay.json` | 历史回放：每个锚点日「只用之前数据」做出的预测 + 之后真实价格（`future` 数组），用于「预测 vs 实际」两条线对照 |
| `data/backtest.json` | 用模型信号做多/空仓的策略净值，与买入持有（buy & hold）对比 |

---

## 6. 准确性 & 诚实基线

| 模型 / 基线 | 21日方向 | 63日方向 |
|---|---|---|
| **RF（本模型）** | **72.1%** | **79.6%** |
| 盲赌「总是涨」（金价上涨日占比，实测自 factors.csv） | 53.6% | 56.9% |
| WGC 朴素因子规则（因子方向加权） | 48.9% | — |

**怎么读**：
- 模型在两个窗口都明显赢过盲赌——说明它**真的学到了东西**，不是趋势红利。
- 63 日准确率高于 21 日，部分来自金价长期上行趋势（趋势本身就有方向性），所以 63 日「赢盲赌」的幅度里含趋势成分；21 日更能体现模型增量。
- **特征重要性** Top：实际利率(12.7%) > 美元1年趋势(9.2%) > 央行净购金(8.9%) > 标普60日(8.7%) > 标普1年(7.8%) > GVZ(6.8%) > 金价年化动量(6.3%)…——宏观变量主导，符合黄金的宏观定价逻辑。

---

## 7. 站点如何渲染

页面（`index.html` + `app.js`）纯静态、纯前端，**不训练、不联网**，只读取上面 3 个 JSON：

1. **信号卡**：最新 `P(up)`、预测涨跌幅区间。
2. **历史回放**：选一个过去日期 → 只用那之前的数据预测未来 21/63 日 → 与真实价格画成「预测（蓝虚线）vs 实际（金实线）」两条线；超出真实数据后只剩预测线。
3. **因子重要性**：条形图。
4. **回测**：策略净值 vs 买入持有。
5. **上传即分析**：用户上传自己的 Excel/CSV，只做技术面描述（MA/动量/回撤/波动率/regime），**不预测**（上传自训练模型已被移除，因其不如盲赌）。

### 7.1 线是「提前算好上传」还是「当场画」？

**结论：数字是离线（Python）算好、存成静态 JSON 上传的；线本身是浏览器每次打开时用 ECharts 实时绘制的。即「预计算端点 + 实时绘制」。**

- Python 离线算出 `signals.json / replay.json / backtest.json` 并 `git push` 到仓库；GitHub Pages 托管这些静态文件。
- 网页打开时，纯前端 `fetch(..., {cache:'no-store'})` 读取这些 JSON（`cache:'no-store'` 只绕过浏览器缓存，**不联网拉新数据**），再交给 ECharts 画图。

**回放页「预测 vs 实际」两条线怎么来的：**

- **实际线（金实线）**：`replay.json` 中的 `gold`（完整历史价）+ 每个回放锚点的 `future`（该日之后的真实价）。前端按所选日期拼接成一条实线。
- **预测线（蓝虚线）**：每条回放点只存**两个端点**——预测日价格 `startP`，以及由预测收益率 `pred_ret` 算出的终点 `startP × (1 + pred_ret/100)`。前端在这两个端点间**画一条蓝色虚直线**，并钉上「+x%」标记。
- 因此「预测路径」是一段**直虚线**（模型只预测 21/63 天窗口的涨跌方向与幅度，不预测逐日路径）。超出真实数据之后（如 8-31 以后），实际线断开、只剩预测虚线，信息栏会提示「真实金价截至 X，其后只有模型预测路径」。

回测页、因子重要性、信号卡同理，均读 JSON 当场渲染。上传 Excel 自分析完全在浏览器本地算 MA/动量/回撤/波动率，不上传服务器、也不碰模型。

---

## 8. 如何重新生成（本地 & 自动）

**本地**：
```bash
cd docs/predictor
python run.py                 # fetch_factors + train_rf
python build_replay.py        # 单独生成 replay.json
```

**每日自动（GitHub Actions）**：
`.github/workflows/refresh.yml` 在 UTC 23:17 触发，自动：装依赖 → 跑上面三步（美盘+沪盘收盘后）→ `git commit` 回写更新后的 JSON → push。也可在 Actions 页面手动 `workflow_dispatch` 触发。
> 美国金价若想随刷新更新，需在仓库 **Settings → Secrets** 配置 `TD_KEY`（Twelvedata 免费 key）；未配置则金价回退到 `gold_history.csv`。

---

## 9. 局限与注意

- **幅度（收益率点估计）误差大**，方向（P(up)）才是可靠部分；不要拿幅度当价格目标。
- 模型是**方向偏置信号**，不是择时交易系统；63 日表现含趋势成分。
- 数据快照冻结在 `as_of`，页面 `fetch` 仅绕过浏览器缓存读本地文件，**不会自己联网拉新数据**——要更新必须重跑管线（本地或 Actions）。
- 沪金版（`../shgold/`）是同一套方法论的移植，因子更贴近「沪金 ≈ 国际金价 × USD/CNY + 国内溢价」的定价恒等式，效果见该目录 README。
