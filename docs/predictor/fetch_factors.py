#!/usr/bin/env python3
"""
fetch_factors.py — 拉取黄金预测原型所需的因子时序。

数据源：
  - 5 个宏观/市场因子：FRED fredgraph.csv（免 API key）
      real_rate = DFII10   10Y TIPS 实际利率
      spx       = NASDAQCOM 美股走势代理（FRED SP500 日线仅自2016，改用纳斯达克综合指数）
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
    # 注：FRED 的 SP500 日线序列仅自 2016-08 起，会截断样本。改用 NASDAQCOM
    # （纳斯达克综合指数，2008 起有日线），作为美股市场走势代理，历史更长且高度相关。
    "spx": "NASDAQCOM",
    "vix": "VIXCLS",
    "dxy": "DTWEXBGS",
    "gvz": "GVZCLS",
}
START = "2008-01-01"  # 拉取更早的宏观因子，配合 gold_history.csv(2011-11起) 使特征样本扩展到 ~13 年
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


def _read_local_gold() -> pd.Series:
    p = os.path.join(DATA, "gold_history.csv")
    if os.path.exists(p):
        df = pd.read_csv(p)
        df.columns = [c.strip() for c in df.columns]
        datecol = df.columns[0]
        df["date"] = pd.to_datetime(df[datecol])
        goldcol = [c for c in df.columns if c.lower() in ("close", "gold", "price", "value")][0]
        return df.set_index("date")[goldcol].astype(float).sort_index()
    return None


def _write_gold(s: pd.Series):
    p = os.path.join(DATA, "gold_history.csv")
    out = s.sort_index().dropna()
    out.index = out.index.strftime("%Y-%m-%d")
    out.index.name = "date"
    out.rename("close").to_frame().to_csv(p)


def _fetch_twelvedata(key: str):
    try:
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
    except Exception as e:
        print("[warn] Twelvedata 拉取失败：", e, file=sys.stderr)
    return None


def _fetch_yahoo(symbol: str):
    """Yahoo Finance 日线（免费、无 key；GitHub Actions 环境可直连）。"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1y"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
        j = r.json()
        res = j["chart"]["result"][0]
        ts = res["timestamp"]
        close = res["indicators"]["quote"][0]["close"]
        idx = pd.to_datetime(ts, unit="s").normalize()
        s = pd.Series(close, index=idx, dtype=float).dropna()
        return s.sort_index()
    except Exception as e:
        print("[warn] Yahoo 拉取失败：", e, file=sys.stderr)
    return None


def _fetch_stooq(symbol: str):
    """Stooq 日线（免费、无 key；Yahoo 失败时的兜底）。"""
    try:
        url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip().lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        goldcol = [c for c in df.columns if c in ("close", "gold", "price")][0]
        return df.set_index("date")[goldcol].astype(float).sort_index()
    except Exception as e:
        print("[warn] Stooq 拉取失败：", e, file=sys.stderr)
    return None


def fetch_gold() -> pd.Series:
    """金价历史（目标变量）。自动更新，无需 key 即可工作：

      1) Twelvedata（若设了 TD_KEY / TWELVEDATA_KEY，最稳）
      2) Yahoo Finance GC=F（免费、无 key，GitHub Actions 可直连）
      3) Stooq xauusd（免费、无 key，兜底）
      4) 本地 data/gold_history.csv（全部在线源失败时，保证不崩）

    无论用哪种方式，新数据都会合并回 gold_history.csv，
    使后续每次运行从「最新快照」继续累积，模型历史不被截断。
    """
    live = None
    key = os.getenv("TD_KEY") or os.getenv("TWELVEDATA_KEY")
    if key:
        live = _fetch_twelvedata(key)
    if live is None:
        live = _fetch_yahoo("GC=F")
    if live is None:
        live = _fetch_stooq("xauusd")
    local = _read_local_gold()
    if live is not None and len(live):
        if local is not None and len(local):
            merged = live.combine_first(local)
            merged = merged[~merged.index.duplicated(keep="first")]
        else:
            merged = live
        merged = merged.sort_index()
        _write_gold(merged)
        return merged
    if local is not None:
        return local
    raise SystemExit(
        "\n[ERROR] 缺少金价历史，且所有在线源均不可用。\n"
        "请放一份 data/gold_history.csv（至少两列：date, close）\n"
    )


def load_cb() -> dict:
    """央行年净购金（吨）：WGC Gold Demand Trends 年度净购金。
    返回 {year: net_tonnes}。使用时取『上一年』值，避免前视（当年总量年底才知）。"""
    p = os.path.join(DATA, "cb_gold.csv")
    out = {}
    if os.path.exists(p):
        c = pd.read_csv(p)
        for _, row in c.iterrows():
            out[int(row["year"])] = float(row["net_tonnes"])
    return out


def build_features(gold: pd.Series, freds: dict) -> pd.DataFrame:
    # 所有序列重采样到金价交易日（业务日），前向填充缺失
    idx = gold.index
    frames = {"gold": gold}
    for name, s in freds.items():
        s = s.reindex(idx, method="ffill").reindex(idx, method="bfill")
        frames[name] = s
    df = pd.DataFrame(frames)

    # 央行净购金：取『上一年』年净购金（避免前视），按交易日填充
    cb = load_cb()
    if cb:
        cb_net = [cb.get(d.year - 1, np.nan) for d in idx]
        df["cb_net"] = pd.Series(cb_net, index=idx).ffill().bfill()
    else:
        df["cb_net"] = np.nan

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
