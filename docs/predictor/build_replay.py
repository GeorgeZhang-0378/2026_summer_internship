#!/usr/bin/env python3
"""
build_replay.py — 生成"历史回放"数据 replay.json。

对历史上每个 walk-forward 点（每 21 天一个），只用该日及之前的数据训练随机森林，
预测未来 21/63 天方向概率，并记录此后真实金价路径。
前端用日期选择器让用户"穿越"到任意历史日，看当时模型怎么预判、后来实际怎么走。
"""
import json
import os
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
df = pd.read_csv(os.path.join(DATA, "factors.csv"), parse_dates=["date"]).set_index("date").sort_index()

FEATURES = ["gold_ret_20", "gold_ret_60", "gold_ret_252", "gold_vol_20", "gold_vol_60",
            "real_rate", "real_rate_chg_60", "dxy_chg_20", "dxy_chg_252", "vix", "vix_chg_20",
            "gvz", "spx_ret_20", "spx_ret_60", "spx_ret_252"]
WIN = {"gold_ret_20": 20, "gold_ret_60": 60, "gold_ret_252": 252, "gold_vol_20": 20, "gold_vol_60": 60,
       "real_rate": 5, "real_rate_chg_60": 60, "dxy_chg_20": 20, "dxy_chg_252": 252, "vix": 5,
       "vix_chg_20": 20, "gvz": 5, "spx_ret_20": 20, "spx_ret_60": 60, "spx_ret_252": 252}


def feas(nn):
    return [f for f in FEATURES if WIN[f] * 1.6 < nn]


n = len(df)
min_train = min(500, max(120, n // 3))

gold_full = [[d.strftime("%Y-%m-%d"), round(float(df["gold"].loc[d]), 2)] for d in df.index]

replay = []
i = min_train
while i < n - 21:
    cutoff = df.index[i]
    sub = df[df.index <= cutoff]
    feats = feas(len(sub))
    entry = {"date": cutoff.strftime("%Y-%m-%d")}
    for h in (21, 63):
        yc = sub[f"dir_{h}"]
        yr = sub[f"target_{h}"]
        X = sub[feats]
        Xtr, ytr_c = X.iloc[:-1].dropna(), yc.iloc[:-1].dropna()
        Xtr, ytr_c = Xtr.align(ytr_c, join="inner", axis=0)
        Xte = X.iloc[[-1]].dropna()
        if len(Xtr) < 120 or Xte.isnull().any().any():
            entry[f"p{h}"] = None
            entry[f"ret{h}"] = None
            entry[f"pred_ret{h}"] = None
            continue
        clf = RandomForestClassifier(n_estimators=300, max_depth=6,
                                     min_samples_leaf=20, random_state=42, n_jobs=-1)
        clf.fit(Xtr, ytr_c)
        p = float(clf.predict_proba(Xte)[0][1])
        tgt = df[f"target_{h}"].get(cutoff)
        # 回归器预测未来收益率（连续值），用于画出"模型预测路径"第三根线
        Xtr_r, ytr_r = X.iloc[:-1].dropna(), yr.iloc[:-1].dropna()
        Xtr_r, ytr_r = Xtr_r.align(ytr_r, join="inner", axis=0)
        reg = RandomForestRegressor(n_estimators=300, max_depth=6,
                                    min_samples_leaf=20, random_state=42, n_jobs=-1)
        reg.fit(Xtr_r, ytr_r)
        pred_ret = float(reg.predict(Xte)[0])
        entry[f"p{h}"] = round(p, 4)
        entry[f"ret{h}"] = None if pd.isna(tgt) else round(float(tgt) * 100, 2)
        entry[f"pred_ret{h}"] = round(pred_ret * 100, 2)
    # 此后真实金价路径（最多 63 个交易日）
    fut = df["gold"].loc[cutoff:].iloc[1:64]
    entry["future"] = [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in fut.items()]
    replay.append(entry)
    i += 21

out = {"gold": gold_full, "replay": replay}
with open(os.path.join(DATA, "replay.json"), "w") as f:
    json.dump(out, f, separators=(",", ":"))

print("replay points:", len(replay), "| gold pts:", len(gold_full))
print("first:", replay[0])
print("last :", replay[-1])
