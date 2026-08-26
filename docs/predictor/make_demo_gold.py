#!/usr/bin/env python3
"""
make_demo_gold.py — 生成【演示用】金价历史 data/gold_history.csv。

⚠️ 这是 SYNTHETIC（合成）数据，仅用于把整条管线（数据→特征→RF→回测→UI）跑通演示。
真实预测请用以下任一方式替换：
  1) 设置环境变量 TD_KEY=你的Twelvedata免费key 后运行 fetch_factors.py
  2) 自己放一份真实 data/gold_history.csv（列为 date, close）
"""
import os, datetime as dt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "gold_history.csv")
START = dt.date(2016, 1, 1)
N = 2600  # ~10 年交易日
rng = np.random.default_rng(42)

# 几何布朗运动：年化漂移 10%，年化波动 16%，叠加两次回撤/反弹 regime
drift = 0.10 / 252
vol = 0.16 / np.sqrt(252)
price = 1060.0
shocks = {600: -0.18, 1100: 0.22, 1700: -0.12, 2200: 0.30}
dates, closes = [], []
d = START
while len(closes) < N:
    if d.weekday() < 5:  # 仅工作日
        shock = shocks.get(len(closes), 0.0)
        ret = drift + vol * rng.standard_normal() + shock / 20.0
        price *= (1 + ret)
        dates.append(d); closes.append(price)
    d += dt.timedelta(days=1)

df = pd.DataFrame({"date": dates, "close": np.round(closes, 2)})
df.to_csv(OUT, index=False)
print(f"[DEMO] 写入 {OUT}  行数={len(df)}  区间 {df.date.iloc[0]} ~ {df.date.iloc[-1]}  末值={df.close.iloc[-1]:.1f}")
