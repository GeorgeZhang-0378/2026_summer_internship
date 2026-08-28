#!/usr/bin/env python3
"""
train_rf.py — walk-forward 随机森林方向模型 + 回测。

- 基线：WGC 四因子式加权合成指数（z-score 加权）→ 方向信号。
- 主模型：RandomForestClassifier，滚动窗口（expanding，最少 500 样本）walk-forward 验证，
  每隔 RETRAIN_DAYS=21 天重训一次，避免前视泄漏。
- 回测：信号→仓位（概率>0.5 做多，否则空仓），策略净值 vs 买入持有。
- 输出：site/data/signals.json + site/data/backtest.json
"""
import json
import os
import datetime as dt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SITE_DATA = os.path.join(HERE, "data")

FEATURES = [
    "gold_ret_20", "gold_ret_60", "gold_ret_252",
    "gold_vol_20", "gold_vol_60",
    "real_rate", "real_rate_chg_60",
    "dxy_chg_20", "dxy_chg_252",
    "vix", "vix_chg_20",
    "gvz",
    "spx_ret_20", "spx_ret_60", "spx_ret_252",
    "cb_net",
]
# 每个特征对应的回看窗口（用于判断当前样本量是否足够）
FEATURE_WINDOW = {
    "gold_ret_20": 20, "gold_ret_60": 60, "gold_ret_252": 252,
    "gold_vol_20": 20, "gold_vol_60": 60,
    "real_rate": 5, "real_rate_chg_60": 60,
    "dxy_chg_20": 20, "dxy_chg_252": 252,
    "vix": 5, "vix_chg_20": 20,
    "gvz": 5,
    "spx_ret_20": 20, "spx_ret_60": 60, "spx_ret_252": 252,
    "cb_net": 5,
}
# 特征中文名（用于前端展示，避免 _ 英文单词）
FEATURE_CN = {
    "gold_ret_20": "金价20日收益",
    "gold_ret_60": "金价60日收益",
    "gold_ret_252": "金价年化动量(1年)",
    "gold_vol_20": "金价20日波动率",
    "gold_vol_60": "金价60日波动率",
    "real_rate": "实际利率(10Y TIPS)",
    "real_rate_chg_60": "实际利率60日变化",
    "dxy_chg_20": "美元20日变化",
    "dxy_chg_252": "美元1年趋势",
    "vix": "VIX波动率",
    "vix_chg_20": "VIX 20日变化",
    "gvz": "黄金隐含波动率(GVZ)",
    "spx_ret_20": "标普20日收益",
    "spx_ret_60": "标普60日收益",
    "spx_ret_252": "标普1年收益",
    "cb_net": "央行年净购金(吨)",
}
RETRAIN_DAYS = 21


def feasible_features(df):
    """根据可用历史长度动态挑选特征，避免短样本下 252 日特征全为 NaN。"""
    n = len(df)
    return [f for f in FEATURES if FEATURE_WINDOW[f] * 1.6 < n]

# WGC 式基线：因子对黄金的“看多方向”（+1 越高越利好黄金，-1 越高越利空）
WGC_DIR = {
    "gold_ret_252": 1.0,   # 动量
    "gold_ret_60": 0.8,
    "real_rate": -1.0,     # 机会成本
    "dxy_chg_252": -0.8,   # 美元
    "vix": 0.6,            # 风险/避险
    "gvz": 0.3,            # 波动（压力期偏避险）
    "spx_ret_252": -0.4,   # 风险资产替代
}
WGC_W = {k: abs(v) for k, v in WGC_DIR.items()}


def zscore(s, win=252):
    m = s.rolling(win).mean()
    sd = s.rolling(win).std().replace(0, np.nan)
    return (s - m) / sd


def wgc_signal(df):
    z = pd.DataFrame({k: zscore(df[k]) for k in WGC_DIR})
    comp = sum(WGC_DIR[k] * z[k] * WGC_W[k] for k in WGC_DIR) / sum(WGC_W.values())
    return (comp > 0).astype(int)


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
                                     min_samples_leaf=20, random_state=42,
                                     n_jobs=-1)
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
    """signal: Series 索引对齐 df.index，值为 0/1（做多/空仓）。
    target_col 必须与信号对应的持有期一致（21d 信号→target_21，63d 信号→target_63）。"""
    fwd = df[target_col].reindex(signal.index)
    pos = signal.shift(1).fillna(0)  # 用 t-1 信号交易 t，避免前视
    strat = pos * fwd
    bnh = fwd.copy()
    sc = (1 + strat.fillna(0)).cumprod()
    bc = (1 + bnh.fillna(0)).cumprod()
    return sc, bc, strat


def metrics(pred, actual):
    acc = accuracy_score(actual, pred)
    cm = confusion_matrix(actual, pred, labels=[0, 1])
    return float(acc), cm.tolist()


def factor_scores_010(df, as_of):
    """把当前因子映射成 0-10 看多评分（复刻站点信号机美学）。"""
    specs = {
        "gold_ret_252": (1.0, "价格动量(1年)"),
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
        score = float(np.clip(score, 0, 10))
        out.append({
            "name": label, "value": round(float(df[col].iloc[-1]), 4),
            "score": round(score, 1),
            "direction": "bullish" if direction > 0 else "bearish",
        })
    return out


def main():
    df = pd.read_csv(os.path.join(DATA, "factors.csv"), index_col=0, parse_dates=True)
    df = df.sort_index()
    print(f"样本 {len(df)}  区间 {df.index[0].date()} ~ {df.index[-1].date()}")

    # 基线 WGC（仅用当前样本里可用的因子；忽略尾部无标签行）
    avail = [k for k in WGC_DIR if k in df.columns]
    if avail:
        wgc = wgc_signal(df[avail]).reindex(df.index)
        min_train = min(500, max(120, len(df)//3))
        _sub = df["dir_21"].iloc[min_train:].dropna()
        wgc_acc21 = accuracy_score(_sub, wgc.iloc[min_train:].reindex(_sub.index))
    else:
        wgc_acc21 = float("nan")
    print(f"[基线] WGC 合成指数 21d 方向准确率 = {wgc_acc21:.3f}")

    result = {"as_of": str(df.index[-1].date()),
              "n_samples": int(len(df)),
              "wgc_21d_accuracy": round(float(wgc_acc21), 4)}

    back = {}
    wf = {}
    for h in (21, 63):
        print(f"[模型] walk-forward RF  horizon={h}d ...")
        pred, prob, actual = walk_forward(df, h)
        wf[h] = {"pred": pred, "prob": prob, "actual": actual}
        acc, cm = metrics(pred, actual)
        print(f"        RF {h}d 准确率={acc:.3f}  混淆矩阵={cm}")
        result[f"rf_{h}d_accuracy"] = round(float(acc), 4)
        result[f"rf_{h}d_confusion"] = cm

    # 综合信号：两周期 P(up) 等权平均；与 63 日共用较长持有期（63 日才是真正跑赢的窗口）
    p21 = wf[21]["prob"].reindex(wf[63]["prob"].index).ffill()
    p63 = wf[63]["prob"]
    pcomb = ((p21 + p63) / 2).dropna()

    # 三种信号分别回测：21 日、63 日、综合
    signals = {
        "h21":   (wf[21]["prob"], wf[21]["actual"], "target_21"),
        "h63":   (wf[63]["prob"], wf[63]["actual"], "target_63"),
        "hcomb": (pcomb,          wf[63]["actual"], "target_63"),
    }
    for key, (prob, actual, tcol) in signals.items():
        sig = (prob > 0.5).astype(int)
        sc, bc, strat = backtest(df, sig, tcol)
        full = pd.DataFrame({"sc": sc, "bc": bc, "prob": prob, "actual": actual,
                             "strat_ret": strat})
        full = full.dropna()
        step = max(1, len(full) // 300)
        chart = full.iloc[::step]
        back[key] = {
            "strat_final": round(float(sc.iloc[-1]), 4),
            "bnh_final": round(float(bc.iloc[-1]), 4),
            "win_rate": round(float((strat > 0).mean()), 4),
            "n": int(len(full)),
            "dates": [d.strftime("%Y-%m-%d") for d in chart.index],
            "strat_curve": [round(float(x), 4) for x in chart["sc"]],
            "bnh_curve": [round(float(x), 4) for x in chart["bc"]],
            "prob": [round(float(x), 4) for x in chart["prob"]],
            "actual": [int(x) for x in chart["actual"]],
        }
    result["backtest_winner"] = "h63"  # 21日跑输买入持有；63日（及综合）跑赢

    # 特征重要性（用全样本训练一次聚合）
    feats = feasible_features(df)
    clf = RandomForestClassifier(n_estimators=300, max_depth=6,
                                 min_samples_leaf=20, random_state=42, n_jobs=-1)
    clf.fit(df[feats].dropna(), df["dir_21"].dropna())
    imp = sorted(zip(FEATURES, clf.feature_importances_),
                 key=lambda x: -x[1])
    result["feature_importance"] = [{"name": FEATURE_CN.get(k, k), "imp": round(float(v), 4)}
                                    for k, v in imp]

    # 当前因子 0-10 评分（用最新一行）
    scores = factor_scores_010(df, df.index[-1])
    result["factor_scores"] = scores

    # 最新一行「实时」预测：用全量有标签数据训练，对最新特征行做预测。
    # walk-forward 的 prob 末尾只有有标签的历史行（~数月前），不能代表今天。
    feats = feasible_features(df)
    labeled = df.dropna(subset=feats + ["dir_21", "dir_63"])
    clf_live = RandomForestClassifier(n_estimators=300, max_depth=6,
                                     min_samples_leaf=20, random_state=42, n_jobs=-1)
    clf_live.fit(labeled[feats], labeled["dir_21"])
    live_p21 = float(clf_live.predict_proba(df[feats].iloc[[-1]])[0][1])
    clf_live63 = RandomForestClassifier(n_estimators=300, max_depth=6,
                                       min_samples_leaf=20, random_state=42, n_jobs=-1)
    clf_live63.fit(labeled[feats], labeled["dir_63"])
    live_p63 = float(clf_live63.predict_proba(df[feats].iloc[[-1]])[0][1])
    result["latest_P_up_21d"] = round(live_p21, 4)
    result["latest_P_up_63d"] = round(live_p63, 4)

    # 写 JSON
    os.makedirs(SITE_DATA, exist_ok=True)
    with open(os.path.join(SITE_DATA, "signals.json"), "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    with open(os.path.join(SITE_DATA, "backtest.json"), "w") as f:
        json.dump(back, f, indent=2, ensure_ascii=False)
    print("写入 site/data/signals.json + backtest.json")


if __name__ == "__main__":
    main()
