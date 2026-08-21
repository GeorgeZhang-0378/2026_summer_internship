# Gold Multi-Factor Forecasting
## 伦敦金 + 上海黄金多因子趋势预测研究

This repository restarts the gold forecasting project from zero with two clearly separated targets and a common research engine.  
本仓库从零重新搭建黄金预测项目，将伦敦金与上海黄金作为两个明确区分的预测标的，同时共享同一套研究与回测框架。

**Primary objective:** forecast 5D / 20D / 60D future gold direction and expected return using point-in-time, leakage-controlled data.  
**核心目标：** 使用严格的 Point-in-Time 数据和防信息泄漏回测，预测未来 5 / 20 / 60 个交易日的方向与预期收益。

The system should output probabilities and confidence, not force a BUY/SELL signal every day.  
系统最终输出的是上涨概率、预期收益、置信度和因子贡献，而不是每天强行给出 BUY/SELL。

---

## 1. Raw data currently available / 当前已有原始数据

| Market | Raw series | Observations | Date range | Native useful fields |
|---|---|---:|---|---|
| London / 伦敦 | `SPTAUUSDOZ.IDC` 伦敦金现 | 13,902 | 1920-01-30 → 2026-08-03 | OHLC |
| Shanghai / 上海 | `AU.SHF` SHFE黄金 | 4,518 | 2008-01-09 → 2026-08-12 | OHLC, settlement, turnover, volume, open interest |

Important: the London Wind file labels price columns with `元`, but the ticker/name indicate London spot gold and the numerical scale is consistent with USD/oz.  
注意：伦敦金原始 Wind 文件的价格列名写有“元”，但代码与名称均指向伦敦金现，数值尺度也对应 USD/oz；处理时不应把该表头理解为人民币。

Important: the Shanghai file is **SHFE gold futures (`AU.SHF`)**, not the Shanghai Gold Benchmark Price published by SGE.  
注意：上海数据是**上期所黄金期货 `AU.SHF`**，不是上海黄金交易所发布的 Shanghai Gold Benchmark Price，因此上海模型应保留期货成交量、持仓量、结算价等本地期货因子。

The raw London turnover and volume columns are zero throughout, so they must not be treated as London liquidity signals.  
伦敦金原始文件中的成交额与成交量全为 0，因此不能把它们当作有效的伦敦流动性因子。

The raw London history begins in 1920, but the default research sample starts in **1980** because the early gold-market regime is not directly comparable to the modern freely traded market; the full raw history remains preserved.  
伦敦金原始历史从 1920 年开始，但默认研究样本从 **1980 年**开始，因为早期黄金市场制度与现代自由交易市场并不直接可比；完整原始历史仍然保留。

---

## 2. Model philosophy / 模型理念

We do **not** start from a complex ML model.  
我们**不**从复杂机器学习模型开始。

We start from economically interpretable factor families, test each one independently out-of-sample, reject unstable factors, then combine only the survivors.  
我们先建立有经济含义的因子家族，逐个进行严格样本外测试，淘汰不稳定因子，再组合通过筛选的因子。

This follows the useful part of the Macquarie QIS framework: distinct sources such as trend, value/mean reversion, volatility, carry/curve, congestion/positioning and defensive/risk signals should be treated as separate information sources rather than duplicated technical indicators.  
这借鉴了 Macquarie QIS 最值得保留的思想：趋势、价值/均值回归、波动率、Carry/曲线、拥挤/持仓与风险防御应被视为不同的信息来源，而不是堆叠大量重复技术指标。

World Gold Council's GRAM framework is also used as an external sanity check for the global factor families: economic expansion, risk & uncertainty, opportunity cost through FX/rates, and momentum/trends.  
世界黄金协会 GRAM 的因子框架也作为全球黄金因子库的外部逻辑校验：经济扩张、风险与不确定性、汇率/利率机会成本，以及动量/趋势。

---

## 3. London vs Shanghai / 两个市场为什么不能完全一样

### London / global engine
London gold has no usable local volume information in the supplied dataset, so the model relies more heavily on:
- price trend and mean reversion
- U.S. real yields
- nominal yields / yield curve
- broad USD
- VIX / cross-asset risk
- inflation breakevens
- credit spreads
- COMEX CFTC positioning
- later: ETF flows / options / volatility surface

### Shanghai overlay
Shanghai gold shares the global gold engine but additionally has:
- SHFE volume
- SHFE open interest
- turnover/liquidity
- settlement-vs-close information
- USD/CNY
- Shanghai-vs-London converted premium/basis
- cross-market lead/lag
- China-specific seasonality
- later: Chinese ETF flows, local physical demand, participant positioning

We therefore use **shared global factors + Shanghai-local overlay**, not two unrelated black boxes.  
因此我们采用**共享全球核心因子 + 上海本地叠加层**，而不是两个毫无关系的黑箱模型。

---

## 4. Repository layout / 仓库结构

```text
gold_multifactor_forecasting/
├── README.md
├── pyproject.toml
├── requirements.txt
├── Makefile
├── config/
│   └── research.yaml
├── data/
│   ├── raw/                 # local Wind files; gitignored by default
│   ├── processed/           # normalized London/Shanghai base/model datasets
│   └── external/            # downloaded FRED/CFTC inputs
├── docs/
│   ├── FACTOR_LIBRARY.md
│   ├── METHODOLOGY.md
│   ├── DATA_SOURCES.md
│   └── RESEARCH_LOG.md
├── factor_tests/
│   ├── 01_momentum.py
│   ├── 02_trend_strength.py
│   ├── ...
│   └── 22_gold_etf_flows.py
├── scripts/
│   ├── 01_profile_raw_data.py
│   ├── 02_build_base_datasets.py
│   ├── 03_download_public_factors.py
│   ├── 04_merge_point_in_time.py
│   ├── 05_run_all_factor_tests.py
│   └── 06_build_factor_audit.py
├── src/goldforecast/
│   ├── data.py
│   ├── feature_utils.py
│   ├── point_in_time.py
│   ├── targets.py
│   └── walkforward.py
├── tests/
│   └── test_smoke.py
└── results/
```

---

## 5. Workflow / 完整研究流程

```text
Wind raw data
     │
     ├── London spot gold
     └── SHFE AU gold
     │
     ▼
Normalize + data audit
     │
     ▼
Download external factors
(FRED + CFTC; later ETF/options/local China)
     │
     ▼
Point-in-time merge
     │
     ▼
Create 5D / 20D / 60D labels
     │
     ▼
Test EACH factor independently
     │
     ▼
Factor Audit Table
     │
     ├── reject unstable / redundant factors
     └── retain robust factors
     │
     ▼
Build factor-family scores
     │
     ▼
London global model
     │
     └── + Shanghai local overlay
     │
     ▼
Purged walk-forward model comparison
     │
     ▼
Probability + expected return + confidence
     │
     ▼
Neutral / bullish / bearish decision layer
     │
     ▼
Frozen live paper test
```

---

## 6. Factor admission gate / 单因子进入正式模型的门槛

Each factor is tested using the same walk-forward engine.  
所有因子必须使用完全相同的 Walk-Forward 引擎测试。

Reported metrics:
- OOS Spearman IC
- ROC-AUC
- balanced accuracy
- Brier score
- fold-by-fold IC
- coefficient sign consistency
- coverage
- recent vs older stability

A factor is **not** accepted merely because full-sample correlation is high.  
因子不能仅因为全样本相关性高就进入正式模型。

A useful research flag is:
- at least 5 valid OOS folds
- AUC around or above 0.52 **or** meaningful OOS IC
- coefficient/sign stability above roughly 60%
- no single fold dominates the result
- clear economic interpretation
- incremental value after adding to the base model

These are research gates, not immutable laws.  
这些是研究筛选门槛，而不是永远固定的“真理”。

---

## 7. Walk-forward / 防泄漏回测

Primary horizon: **20 trading days**.  
主预测周期：**20 个交易日**。

Default:
- minimum train: 756 observations
- test block: 63 observations
- purge: horizon
- embargo: 5 observations
- expanding window initially
- later compare rolling 5Y / 8Y

For every test fold:
1. remove labels that overlap the test window
2. fit scaler only on training data
3. fit model only on training data
4. predict the untouched next block
5. concatenate all OOS predictions
6. evaluate only OOS results

---

## 8. Point-in-time convention / 时间可得性规则

The v1 forecast timestamp is defined as **after the relevant local trading day has closed**.  
v1 将预测时点定义为**相应市场当天收盘之后**。

To be conservative:
- daily U.S./FRED factors are lagged by one calendar day before use
- CFTC Tuesday positions are treated as available approximately three calendar days later
- Shanghai same-day volume/OI/settlement may be used for forecasts made after the Shanghai close
- Shanghai's London reference uses previously available London information rather than a London close that had not occurred yet

This is deliberately conservative; later versions can use exact publication timestamps.  
这个设定故意偏保守；后续版本可以升级为真实发布时间戳。

---

## 9. Public data sources / 可自动下载的公共数据源

### FRED
The downloader currently supports:
- `DFII10` — U.S. 10Y real yield
- `DGS2` — U.S. 2Y Treasury yield
- `DGS10` — U.S. 10Y Treasury yield
- `T10YIE` — U.S. 10Y breakeven inflation
- `DTWEXBGS` — broad U.S. dollar index
- `VIXCLS` — VIX
- `BAMLH0A0HYM2` — U.S. high-yield option-adjusted spread
- `DEXCHUS` — CNY per USD

### CFTC
- Disaggregated Futures Only
- GOLD / COMEX
- managed-money long, short and net positioning

### Research references
- World Gold Council — Gold Return Attribution Model:
  https://www.gold.org/goldhub/tools/gold-return-attribution-model
- World Gold Council — Gold Mid-Year Outlook 2026:
  https://www.gold.org/goldhub/research/gold-mid-year-outlook-2026
- LBMA Gold Price:
  https://www.lbma.org.uk/prices-and-data/lbma-gold-price
- Shanghai Gold Exchange benchmark data:
  https://en.sge.com.cn/data_BenchmarkPrice
- CFTC COT:
  https://publicreporting.cftc.gov/Commitments-of-Traders/Disaggregated-Futures-Only/72hh-3qpy
- FRED:
  https://fred.stlouisfed.org/

The SGE benchmark is included as a research reference, but it is **not the current Shanghai prediction target**; our supplied target is SHFE `AU.SHF`.  
SGE Benchmark 目前只是研究参考，而**不是当前上海预测标的**；当前预测标的是用户提供的 SHFE `AU.SHF`。

---

## 10. Quick start / 快速开始

Create environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The downloaded package already contains the two local raw files and normalized CSVs for convenience.  
当前下载包为了方便已经包含两份本地原始文件与标准化 CSV。

Because the raw data appears to come from Wind, `.gitignore` excludes raw and derived data by default.  
由于原始数据来源看起来是 Wind，`.gitignore` 默认不会把原始及衍生数据推送到 GitHub。

Build/rebuild local base data:

```bash
python scripts/02_build_base_datasets.py
```

Download public factors:

```bash
python scripts/03_download_public_factors.py
```

Merge point-in-time datasets:

```bash
python scripts/04_merge_point_in_time.py
```

Run all factor tests for London:

```bash
python scripts/05_run_all_factor_tests.py --market london --horizon 20
```

Run all factor tests for Shanghai:

```bash
python scripts/05_run_all_factor_tests.py --market shanghai --horizon 20
```

Create the audit table:

```bash
python scripts/06_build_factor_audit.py --market london --horizon 20
python scripts/06_build_factor_audit.py --market shanghai --horizon 20
```

---

## 11. What comes after factor testing? / 因子测试之后

Do not jump directly to XGBoost.  
不要直接跳到 XGBoost。

Once the audit table exists:
1. remove redundant factors
2. group survivors into economic families
3. construct family scores
4. compare logistic / linear / HistGradientBoosting baselines
5. calibrate probabilities
6. build Shanghai local overlay
7. freeze the model for forward paper testing

The final daily output should look like:

```text
Market: Shanghai AU
Horizon: 20D
P(up): 0.63
Expected return: +1.9%
Confidence: Medium-High
Regime: Trending / elevated volatility

Positive drivers:
+ Global gold momentum
+ Broad USD weakness
+ SHFE open-interest confirmation

Negative drivers:
- Rising real yields
- Shanghai/London premium already rich

Decision: Bullish
```

If `P(up)` is around 0.50, the correct output is **neutral**, not a forced trade.  
如果 `P(up)` 接近 0.50，正确输出应当是**中性**，而不是强行产生交易信号。

---

## 12. Current status / 当前状态

**Phase 0 is complete:** clean repository architecture, local data normalization, external-data downloader, point-in-time merge framework, 22 independent factor-test modules, shared purged walk-forward engine, audit-table builder and smoke tests.  
**Phase 0 已完成：**全新仓库架构、本地数据标准化、公共因子下载器、Point-in-Time 合并框架、22 个独立单因子测试模块、统一 Purged Walk-Forward 引擎、因子审计表生成器和 Smoke Test。

**Phase 1 is next:** run the real factor tests, inspect failures and stability, then decide what actually survives into the first production candidate.  
**下一阶段是 Phase 1：**用真实数据正式运行每一个因子测试，检查稳定性与失败原因，然后决定哪些因子真正进入第一版候选预测模型。
