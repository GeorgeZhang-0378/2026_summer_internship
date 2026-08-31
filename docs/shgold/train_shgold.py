#!/usr/bin/env python3
"""
train_shgold.py — 沪金 walk-forward 随机森林方向模型 + 回测（对标美国黄金原型方法论）。

特征（围绕“沪金 = 国际金价 × USD/CNY + 国内溢价”构造）：
  沪金技术面：shgold_ret_20/60/252, shgold_vol_20/60
  汇率：usdcny_chg_20/252（人民币贬值→沪金涨）
  国际金价：intl_ret_20/60/252（主驱动）
  国内溢价：premium_chg_60（均值回复）
  全球宏观（同源美国模型）：real_rate, real_rate_chg_60, dxy_chg_20/252, vix, vix_chg_20, gvz, spx_ret_20/60/252

标签：沪金未来 21/63 日收益率符号（dir_*）与收益率本身（target_*）。

输出：data/signals_shgold.json + data/backtest_shgold.json
"""
import json
import os
import datetime as dt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score, confusion_matrix

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
RETRAIN_DAYS = 21

FEATURES = [
    "shgold_ret_20", "shgold_ret_60", "shgold_ret_252",
    "shgold_vol_20", "shgold_vol_60",
    "usdcny_chg_20", "usdcny_chg_252",
    "intl_ret_20", "intl_ret_60", "intl_ret_252",
    "premium_chg_60",
    "real_rate", "real_rate_chg_60",
    "dxy_chg_20", "dxy_chg_252",
    "vix", "vix_chg_20", "gvz",
    "spx_ret_20", "spx_ret_60", "spx_ret_252",
]
FEATURE_WINDOW = {
    "shgold_ret_20": 20, "shgold_ret_60": 60, "shgold_ret_252": 252,
    "shgold_vol_20": 20, "shgold_vol_60": 60,
    "usdcny_chg_20": 20, "usdcny_chg_252": 252,
    "intl_ret_20": 20, "intl_ret_60": 60, "intl_ret_252": 252,
    "premium_chg_60": 60,
    "real_rate": 5, "real_rate_chg_60": 60,
    "dxy_chg_20": 20, "dxy_chg_252": 252,
    "vix": 5, "vix_chg_20": 20, "gvz": 5,
    "spx_ret_20": 20, "spx_ret_60": 60, "spx_ret_252": 252,
}
FEATURE_CN = {
    "shgold_ret_20": "沪金20日收益", "shgold_ret_60": "沪金60日收益", "shgold_ret_252": "沪金年化动量(1年)",
    "shgold_vol_20": "沪金20日波动率", "shgold_vol_60": "沪金60日波动率",
    "usdcny_chg_20": "人民币20日变化", "usdcny_chg_252": "人民币1年趋势",
    "intl_ret_20": "国际金价20日收益", "intl_ret_60": "国际金价60日收益", "intl_ret_252": "国际金价1年收益",
    "premium_chg_60": "国内溢价60日变化",
    "real_rate": "实际利率(10Y TIPS)", "real_rate_chg_60": "实际利率60日变化",
    "dxy_chg_20": "美元20日变化", "dxy_chg_252": "美元1年趋势",
    "vix": "VIX波动率", "vix_chg_20": "VIX 20日变化", "gvz": "黄金隐含波动率(GVZ)",
    "spx_ret_20": "标普20日收益", "spx_ret_60": "标普60日收益", "spx_ret_252": "标普1年收益",
}


def build_features(df):
    s = df["shgold"]
    r = s.pct_change()
    out = pd.DataFrame(index=df.index)
    out["shgold_ret_20"] = r.rolling(20).sum()
    out["shgold_ret_60"] = r.rolling(60).sum()
    out["shgold_ret_252"] = r.rolling(252).sum()
    out["shgold_vol_20"] = r.rolling(20).std() * np.sqrt(252)
    out["shgold_vol_60"] = r.rolling(60).std() * np.sqrt(252)
    out["usdcny_chg_20"] = df["usdcny"].pct_change(20)
    out["usdcny_chg_252"] = df["usdcny"].pct_change(252)
    ir = df["intl_gold"].pct_change()
    out["intl_ret_20"] = ir.rolling(20).sum()
    out["intl_ret_60"] = ir.rolling(60).sum()
    out["intl_ret_252"] = ir.rolling(252).sum()
    out["premium_chg_60"] = df["premium"].pct_change(60)
    out["real_rate"] = df["real_rate"]
    out["real_rate_chg_60"] = df["real_rate"].diff(60)
    out["dxy_chg_20"] = df["dxy"].pct_change(20)
    out["dxy_chg_252"] = df["dxy"].pct_change(252)
    out["vix"] = df["vix"]
    out["vix_chg_20"] = df["vix"].pct_change(20)
    out["gvz"] = df["gvz"]
    sr = df["spx"].pct_change()
    out["spx_ret_20"] = sr.rolling(20).sum()
    out["spx_ret_60"] = sr.rolling(60).sum()
    out["spx_ret_252"] = sr.rolling(252).sum()
    # 标签：沪金未来收益
    out["target_21"] = s.pct_change(21).shift(-21)
    out["target_63"] = s.pct_change(63).shift(-63)
    out["dir_21"] = (out["target_21"] > 0).astype(int)
    out["dir_63"] = (out["target_63"] > 0).astype(int)
    out["gold"] = s
    return out


def feasible_features(df):
    n = len(df)
    return [f for f in FEATURES if FEATURE_WINDOW[f] * 1.6 < n]


def walk_forward(df, horizon):
    y = df[f"dir_{horizon}"]
    feats = feasible_features(df)
    X = df[feats]
    preds, probs, dates = [], [], []
    min_train = min(500, max(120, len(df) // 3))
    i = min_train
    n = len(df)
    while i < n - horizon:
        Xtr, ytr = X.iloc[:i], y.iloc[:i]
        Xte, yte = X.iloc[[i]], y.iloc[[i]]
        clf = RandomForestClassifier(n_estimators=300, max_depth=6,
                                     min_samples_leaf=20, random_state=42, n_jobs=-1)
        clf.fit(Xtr, ytr)
        p = clf.predict_proba(Xte)[0]
        probs.append(float(p[1]))
        preds.append(int(clf.predict(Xte)[0]))
        dates.append(df.index[i])
        i += RETRAIN_DAYS
    return (pd.Series(preds, index=dates, name="pred"),
            pd.Series(probs, index=dates, name="prob"),
            pd.Series(y.reindex(dates).values, index=dates, name="actual"))


def backtest(df, signal, target_col="target_21"):
    fwd = df[target_col].reindex(signal.index)
    pos = signal.shift(1).fillna(0)
    strat = pos * fwd
    bnh = fwd.copy()
    sc = (1 + strat.fillna(0)).cumprod()
    bc = (1 + bnh.fillna(0)).cumprod()
    return sc, bc, strat


def metrics(pred, actual):
    acc = accuracy_score(actual, pred)
    cm = confusion_matrix(actual, pred, labels=[0, 1])
    return float(acc), cm.tolist()


def zscore(s, win=252):
    m = s.rolling(win).mean()
    sd = s.rolling(win).std().replace(0, np.nan)
    return (s - m) / sd


def factor_scores_010(df):
    specs = {
        "intl_ret_252": (1.0, "国际金价动量(1年)"),
        "usdcny_chg_252": (1.0, "人民币年趋势(贬值利多)"),
        "real_rate": (-1.0, "实际利率"),
        "dxy_chg_252": (-1.0, "美元趋势(1年)"),
        "vix": (0.8, "波动率/避险"),
        "gvz": (0.3, "黄金隐含波动率"),
        "spx_ret_252": (-0.4, "标普(1年)"),
    }
    out = []
    for col, (direction, label) in specs.items():
        z = zscore(df[col]).iloc[-1]
        if not np.isfinite(z):
            z = 0.0
        score = 5 + 5.0 * direction * np.tanh(z / 2.0)
        out.append({"name": label, "value": round(float(df[col].iloc[-1]), 4),
                    "score": round(float(np.clip(score, 0, 10)), 1),
                    "direction": "bullish" if direction > 0 else "bearish"})
    return out


def main():
    raw = pd.read_csv(os.path.join(DATA, "shgold_factors.csv"), index_col=0, parse_dates=True).sort_index()
    df = build_features(raw)
    print(f"样本 {len(df)}  区间 {df.index[0].date()} ~ {df.index[-1].date()}")

    # 盲赌“总是涨”基线（用真实沪金未来收益符号）
    base = df.dropna(subset=["dir_21"])
    always_up21 = float((base["dir_21"] == 1).mean())
    always_up63 = float((df.dropna(subset=["dir_63"])["dir_63"] == 1).mean())
    print(f"[基线] 沪金盲赌总是涨：21d={always_up21:.3f}  63d={always_up63:.3f}")

    result = {"as_of": str(df.index[-1].date()), "n_samples": int(len(df)),
              "always_up_21d": round(always_up21, 4), "always_up_63d": round(always_up63, 4)}

    back, wf = {}, {}
    for h in (21, 63):
        pred, prob, actual = walk_forward(df, h)
        wf[h] = {"pred": pred, "prob": prob, "actual": actual}
        acc, cm = metrics(pred, actual)
        print(f"[模型] RF {h}d 准确率={acc:.3f}  混淆矩阵={cm}")
        result[f"rf_{h}d_accuracy"] = round(acc, 4)
        result[f"rf_{h}d_confusion"] = cm

    p21 = wf[21]["prob"].reindex(wf[63]["prob"].index).ffill()
    p63 = wf[63]["prob"]
    pcomb = ((p21 + p63) / 2).dropna()
    signals = {
        "h21": (wf[21]["prob"], wf[21]["actual"], "target_21"),
        "h63": (wf[63]["prob"], wf[63]["actual"], "target_63"),
        "hcomb": (pcomb, wf[63]["actual"], "target_63"),
    }
    for key, (prob, actual, tcol) in signals.items():
        sig = (prob > 0.5).astype(int)
        sc, bc, strat = backtest(df, sig, tcol)
        full = pd.DataFrame({"sc": sc, "bc": bc, "prob": prob, "actual": actual, "strat_ret": strat}).dropna()
        step = max(1, len(full) // 300)
        chart = full.iloc[::step]
        back[key] = {
            "strat_final": round(float(sc.iloc[-1]), 4), "bnh_final": round(float(bc.iloc[-1]), 4),
            "win_rate": round(float((strat > 0).mean()), 4), "n": int(len(full)),
            "dates": [d.strftime("%Y-%m-%d") for d in chart.index],
            "strat_curve": [round(float(x), 4) for x in chart["sc"]],
            "bnh_curve": [round(float(x), 4) for x in chart["bc"]],
            "prob": [round(float(x), 4) for x in chart["prob"]],
            "actual": [int(x) for x in chart["actual"]],
        }
    result["backtest_winner"] = "h63"

    feats = feasible_features(df)
    labeled = df.dropna(subset=feats + ["dir_21"])
    clf = RandomForestClassifier(n_estimators=300, max_depth=6, min_samples_leaf=20, random_state=42, n_jobs=-1)
    clf.fit(labeled[feats], labeled["dir_21"])
    imp = sorted(zip(FEATURES, clf.feature_importances_), key=lambda x: -x[1])
    result["feature_importance"] = [{"name": FEATURE_CN.get(k, k), "imp": round(float(v), 4)} for k, v in imp]

    result["factor_scores"] = factor_scores_010(df)

    labeled = df.dropna(subset=feats + ["dir_21", "dir_63"])
    clf21 = RandomForestClassifier(n_estimators=300, max_depth=6, min_samples_leaf=20, random_state=42, n_jobs=-1)
    clf21.fit(labeled[feats], labeled["dir_21"])
    result["latest_P_up_21d"] = round(float(clf21.predict_proba(df[feats].iloc[[-1]])[0][1]), 4)
    clf63 = RandomForestClassifier(n_estimators=300, max_depth=6, min_samples_leaf=20, random_state=42, n_jobs=-1)
    clf63.fit(labeled[feats], labeled["dir_63"])
    result["latest_P_up_63d"] = round(float(clf63.predict_proba(df[feats].iloc[[-1]])[0][1]), 4)

    last_feats = df[feats].iloc[[-1]]
    last_gold = float(df["gold"].iloc[-1])
    result["latest_gold"] = round(last_gold, 2)
    for h in (21, 63):
        tcol = f"target_{h}"
        rl = df.dropna(subset=feats + [tcol])
        reg = RandomForestRegressor(n_estimators=300, max_depth=6, min_samples_leaf=20, random_state=42, n_jobs=1)
        reg.fit(rl[feats], rl[tcol].values)
        pred = float(reg.predict(last_feats)[0]) * 100.0
        band = float(np.std(rl[tcol].values)) * 100.0
        result[f"latest_pred_ret_{h}d"] = round(pred, 2)
        result[f"latest_pred_ret_{h}d_band"] = round(band, 2)
        result[f"latest_target_price_{h}d"] = round(last_gold * (1 + pred / 100), 2)
        print(f"        量级预测 {h}d: 收益≈{pred:+.2f}%  历史典型波动±{band:.2f}%  目标价位≈{result[f'latest_target_price_{h}d']}")

    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "signals_shgold.json"), "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    with open(os.path.join(DATA, "backtest_shgold.json"), "w") as f:
        json.dump(back, f, indent=2, ensure_ascii=False)
    print("写入 data/signals_shgold.json + backtest_shgold.json")


if __name__ == "__main__":
    main()
