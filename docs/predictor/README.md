# 黄金方向预测原型 · Gold Direction Predictor

> 基于 FRED 宏观因子 + walk-forward 随机森林的黄金价格方向预测与回测原型。可独立运行，也可嵌入原 `2026_summer_internship` 站点。

---

## 0. 重要说明：DEMO 数据 vs 真实数据

**当前仓库里的 `data/gold_history.csv` 是演示用合成数据**（运行 `make_demo_gold.py` 生成），仅用于把整条管线（数据 → 特征 → RF → 回测 → UI）跑通并展示界面。

**要获得真实预测结果，请替换为真实金价历史**：
1. **推荐**：到 [twelvedata.com](https://twelvedata.com) 注册免费账号，获取 API key，复制 `.env.example` 为 `.env` 并填入 `TD_KEY`。然后删除/覆盖 `data/gold_history.csv`，重新运行 `fetch_factors.py`，即可自动拉取真实 XAU/USD 日度历史。
2. 或自己准备 `data/gold_history.csv`，格式：
   ```csv
   date,close
   2024-01-02,2050.00
   2024-01-03,2045.00
   ...
   ```

---

## 1. 技术栈

- Python 3.13 + pandas + scikit-learn + requests
- ECharts 5（纯前端图表，CDN 引入）
- 静态 HTML/JS，可直接部署到 GitHub Pages

## 2. 项目结构

```
gold-predictor/
├── fetch_factors.py       # 拉取 FRED 免 key 因子 + 金价历史
├── train_rf.py            # walk-forward RF + 回测，输出 JSON
├── make_demo_gold.py      # 生成演示用合成金价（首次运行用）
├── run.py                 # 一键跑：fetch + train（带 demo 自动兜底）
├── .env.example           # 配置模板
├── data/
│   ├── factors.csv        # 特征与标签表（生成）
│   └── gold_history.csv   # 金价历史（真实或 demo）
└── site/                  # 可部署的仪表盘
    ├── index.html
    ├── app.js
    └── data/              # signals.json + backtest.json（生成）
```

## 3. 数据源

| 因子 | 来源 | 是否需要 key | 备注 |
|------|------|-------------|------|
| 10Y 实际利率 (TIPS) | FRED `DFII10` | ❌ 免 key | `fredgraph.csv` 直接下载 |
| 标普 500 | FRED `SP500` | ❌ | 同上 |
| VIX | FRED `VIXCLS` | ❌ | 同上 |
| 广义美元指数 | FRED `DTWEXBGS` | ❌ | 同上 |
| 黄金隐含波动率 GVZ | FRED `GVZCLS` | ❌ | 同上 |
| XAU/USD 金价历史 | Twelvedata | ✅ 免费 key | 或本地 CSV |

## 4. 快速开始

### 4.1 安装依赖

```bash
python -m pip install pandas numpy scikit-learn requests
```

### 4.2 演示运行（零 key）

```bash
cd gold-predictor
python make_demo_gold.py      # 生成 demo 金价
python fetch_factors.py       # 拉 FRED 因子 + 读 demo 金价
python train_rf.py            # 训练 + 回测 → 生成 site/data/*.json
```

### 4.3 真实运行（需 Twelvedata 免费 key）

```bash
cp .env.example .env
# 编辑 .env，填入 TD_KEY
rm data/gold_history.csv      # 如果 demo 文件存在，删掉以使用 Twelvedata
python fetch_factors.py
python train_rf.py
```

### 4.4 一键脚本

```bash
python run.py
```

- 若检测到 `TD_KEY` 或 `data/gold_history.csv`，直接使用真实金价。
- 否则自动生成 demo 金价并继续，同时打印明显警告。

### 4.5 本地查看仪表盘

```bash
cd site
python -m http.server 8771 --bind 127.0.0.1
# 浏览器打开 http://127.0.0.1:8771/
```

---

## 5. 模型说明

- **特征窗口**：20 / 60 / 252 个交易日（≈1月 / 1季 / 1年），符合趋势预测惯例。
- **标签**：未来 21 日 / 63 日的金价收益符号（`shift(-h)` 保证无前视泄漏）。
- **基线**：WGC 式因子合成指数（实际利率、美元、动量、VIX/GVZ、标普）。
- **主模型**：`RandomForestClassifier`，**walk-forward 滚动窗口**验证（每 21 天重训一次，避免前视泄漏与过拟合）。
- **回测**：概率 > 0.5 时做多黄金，否则空仓；对比买入持有。
- **动态特征**：当数据较短（< 400 天）时，自动剔除 252 日特征，确保仍可运行。

---

## 6. 部署到 GitHub Pages

```bash
# 方案 A：作为现有站点的子目录
# 把 gold-predictor/site/ 下全部内容复制到 2026_summer_internship/docs/gold-predictor/
cp -R site/* ../2026_summer_internship/docs/gold-predictor/

# 方案 B：独立仓库
# 创建新 repo，把 site/ 内容推到 main 分支，启用 Pages。
```

建议配合 **GitHub Actions 每日 cron**：每天自动运行 `fetch_factors.py` + `train_rf.py`，刷新 `site/data/*.json`，实现准实时因子更新，无需维护后端。

---

## 7. 已知局限与改进方向

- **金价历史是唯一需要 key 的输入**；其余核心因子已全部免 key。
- WGC 央行购金、ETF 资金流、黄金供需没有公开 API，目前未纳入模型；可作为未来手工/爬取因子加入。
- 月度/季度因子频率较低，可扩展为混频模型。
- 可尝试加入技术指标（RSI、MACD、布林带）作为额外特征。

---

## 8. 免责声明

`make_demo_gold.py` 生成的金价为**随机过程模拟**，产生的回测结果仅供界面演示，不构成投资建议。真实预测必须使用真实金价历史。
