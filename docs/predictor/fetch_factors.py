#!/usr/bin/env python3
"""
fetch_factors.py — 拉取黄金预测原型所需的因子时序。

数据源：
  - 5 个宏观/市场因子：FRED fredgraph.csv（免 API key）
      real_rate = DFII10   10Y TIPS 实际利率
      spx       = SP500    标普500
      vix       = VIXCLS   VIX 波动率
      dxy       = DTWEXBGS 贸易加权美元指数（广义）
      gvz       = GVZCLS   CBOE 黄金隐含波动率
  - 金价历史（目标变量）：Twelvedata 免费 key（env TD_KEY）或本地 data/gold_history.csv

特征窗口：20 / 60 / 252 个交易日（≈1月 / 1季 / 1年），符合预测建模惯例。
标签：未来 21 日 / 63 日的金价收益符号（无前视泄漏：用 shift(-h)）。

产出：data/factors.csv
"""
import io
import os
import sys
import datetime as dt
import numpy as np
import pandas as pd
import requests

FRED_SERIES = {
    "real_rate": "DFII10",
    "spx": "SP500",
    "vix": "VIXCLS",
    "dxy": "DTWEXBGS",
    "gvz": "GVZCLS",
}
START = "2016-01-01"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def fetch_fred(series_id: str, start: str = START) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    valcol = [c for c in df.columns if c != "observation_date"][0]
    out = df.rename(columns={valcol: "v"})[["observation_date", "v"]]
    out["date"] = pd.to_datetime(out["observation_date"])
    out = out.dropna(subset=["v"]).set_index("date")["v"].astype(float)
    return out.sort_index()


def fetch_gold() -> pd.Series:
    """金价历史：优先 Twelvedata key，其次本地 CSV。"""
    key = os.getenv("TD_KEY") or os.getenv("TWELVEDATA_KEY")
    if key:
        url = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD"
               f"&interval=1day&outputsize=4000&apikey={key}")
        r = requests.get(url, timeout=40)
        j = r.json()
        if "values" in j:
            df = pd.DataFrame(j["values"])
            df["date"] = pd.to_datetime(df["datetime"])
            df["gold"] = df["close"].astype(float)
            return df.set_index("date")["gold"].sort_index()
        print("[warn] Twelvedata 返回错误：", j.get("message", j), file=sys.stderr)
    p = os.path.join(DATA, "gold_history.csv")
    if os.path.exists(p):
        df = pd.read_csv(p)
        df.columns = [c.strip() for c in df.columns]
        datecol = df.columns[0]
        df["date"] = pd.to_datetime(df[datecol])
        goldcol = [c for c in df.columns if c.lower() in ("close", "gold", "price", "value")][0]
        return df.set_index("date")[goldcol].astype(float).sort_index()
    raise SystemExit(
        "\n[ERROR] 缺少金价历史。二选一：\n"
        "  1) 设置环境变量 TD_KEY=你的Twelvedata免费key（https://twelvedata.com 注册即用）\n"
        "  2) 放一份 data/gold_history.csv（至少两列：date, close）\n"
    )


def build_features(gold: pd.Series, freds: dict) -> pd.DataFrame:
    # 所有序列重采样到金价交易日（业务日），前向填充缺失
    idx = gold.index
    frames = {"gold": gold}
    for name, s in freds.items():
        s = s.reindex(idx, method="ffill").reindex(idx, method="bfill")
        frames[name] = s
    df = pd.DataFrame(frames)

    g = df["gold"]
    ret = g.pct_change()
    df["gold_ret_20"] = g.pct_change(20)
    df["gold_ret_60"] = g.pct_change(60)
    df["gold_ret_252"] = g.pct_change(252)
    df["gold_vol_20"] = ret.rolling(20).std() * np.sqrt(252)
    df["gold_vol_60"] = ret.rolling(60).std() * np.sqrt(252)

    df["real_rate"] = df["real_rate"]
    df["real_rate_chg_60"] = df["real_rate"].diff(60)
    df["dxy_chg_20"] = df["dxy"].pct_change(20)
    df["dxy_chg_252"] = df["dxy"].pct_change(252)
    df["vix"] = df["vix"]
    df["vix_chg_20"] = df["vix"].diff(20)
    df["gvz"] = df["gvz"]
    df["spx_ret_20"] = df["spx"].pct_change(20)
    df["spx_ret_60"] = df["spx"].pct_change(60)
    df["spx_ret_252"] = df["spx"].pct_change(252)

    # 标签：未来 21 / 63 日收益符号（shift(-h) 保证无前视）
    df["target_21"] = (g.shift(-21) / g - 1)
    df["target_63"] = (g.shift(-63) / g - 1)
    df["dir_21"] = (df["target_21"] > 0).astype(int)
    df["dir_63"] = (df["target_63"] > 0).astype(int)

    # 仅丢弃「特征」为 NaN 的引导行；保留尾部无标签行（未来收益未知），
    # 供 train_rf 对「最新一行」做实时预测，避免 as_of 被标签前视截短到数月前。
    feat_cols = [c for c in df.columns if not c.startswith(("dir_", "target_"))]
    return df.dropna(subset=feat_cols)


def main():
    print("[1/3] 拉取 FRED 因子（免 key）…")
    freds = {name: fetch_fred(sid) for name, sid in FRED_SERIES.items()}
    for n, s in freds.items():
        print(f"      {n:10s} 行数={len(s):5d}  最新={s.iloc[-1]:.3f} @ {s.index[-1].date()}")

    print("[2/3] 拉取金价历史（目标变量）…")
    gold = fetch_gold()
    print(f"      gold 行数={len(gold):5d}  最新={gold.iloc[-1]:.1f} @ {gold.index[-1].date()}")

    print("[3/3] 构造特征与标签（20/60/252 窗口）…")
    df = build_features(gold, freds)
    out = os.path.join(DATA, "factors.csv")
    df.to_csv(out)
    print(f"      写入 {out}  样本数={len(df)}  区间 {df.index[0].date()} ~ {df.index[-1].date()}")
    print("      上涨占比 21d=%.1f%%  63d=%.1f%%" % (
        100 * df["dir_21"].mean(), 100 * df["dir_63"].mean()))


if __name__ == "__main__":
    main()
