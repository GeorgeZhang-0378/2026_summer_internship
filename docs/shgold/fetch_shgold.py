#!/usr/bin/env python3
"""
fetch_shgold.py — 拉取沪金预测所需因子时序。

数据源（全部无需 API key，且带兜底，CI 中任一源失败也不致整步崩溃）：
  - 沪金价格：Sina 期货行情 AU0（SHFE 黄金主力连续），日线，2008 起。失败则用
    “国际金价 × USD/CNY ÷ 31.1035 + 上一已知溢价” 推导补齐最新交易日。
  - USD/CNY：FRED DEXCHUS（免 key）。
  - 国际金价（USD/oz）：优先复用 ../predictor/data/gold_history.csv
    （美国黄金原型已抓取的最新历史）；若该文件缺失则按 TD_KEY→Yahoo→Stooq 兜底拉取。
  - 全球宏观因子（同源美国模型）：FRED DFII10/NASDAQCOM/VIXCLS/DTWEXBGS/GVZCLS

核心恒等式：沪金(元/克) ≈ 国际金价(USD/oz) × USD/CNY ÷ 31.1035(克/盎司) + 国内溢价
  => 国际金价收益率、ΔUSD/CNY、国内溢价 是沪金最主要的三类驱动；外加全球宏观（实际利率/美元/VIX/GVZ）。

产出：data/shgold_factors.csv（与既有文件按日期合并，保留完整历史、补齐最新交易日）。
"""
import io, os, sys
import numpy as np, pandas as pd, requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
GOLD_HISTORY = os.path.join(HERE, "..", "predictor", "data", "gold_history.csv")
START = "2008-01-01"

# 沪金标的：SHFE 黄金主力连续（sina 代码 AU0）。
SYMBOL = "AU0"
SINA_URL = ("https://stock2.finance.sina.com.cn/futures/api/json.php/"
            f"InnerFuturesNewService.getDailyKLine?symbol={SYMBOL}")

# 全球宏观因子（与美国黄金模型同源，便于对比）
FRED_SERIES = {
    "real_rate": "DFII10",     # 10Y TIPS 实际利率
    "spx": "NASDAQCOM",        # 美股代理（纳斯达克综合）
    "vix": "VIXCLS",           # VIX 波动率
    "dxy": "DTWEXBGS",          # 贸易加权美元指数（广义）
    "gvz": "GVZCLS",           # CBOE 黄金隐含波动率
}


def fetch_shgold_sina(symbol=SYMBOL):
    """沪金价格（SHFE AU0）。失败返回 (None, err)。"""
    try:
        r = requests.get(SINA_URL, timeout=25,
                         headers={"User-Agent": "Mozilla/5.0",
                                  "Referer": "https://finance.sina.com.cn"})
        r.raise_for_status()
        rows = r.json()  # list of dicts: d,o,h,l,c,v,p,s
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["d"])
        df["close"] = df["c"].astype(float)
        return df[["date", "close"]].rename(columns={"close": "shgold"}).sort_values("date"), None
    except Exception as e:
        return None, e


def fetch_fred(series_id, start=START):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    s = pd.read_csv(io.StringIO(r.text), skiprows=1)
    s.columns = ["date", series_id]
    s["date"] = pd.to_datetime(s["date"])
    return s.set_index("date")[series_id].astype(float)


def fetch_yahoo_series(symbol, rng="5y"):
    """Yahoo 日线收盘价序列（CI 环境可直连；本沙箱可能被墙，会回退）。"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={rng}"
    r = requests.get(url, timeout=40, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    close = res["indicators"]["quote"][0]["close"]
    s = pd.Series(close, index=pd.to_datetime(ts, unit="s")).dropna()
    s.index = s.index.normalize()  # 去掉 Yahoo 时间戳的时分秒，避免同日多行
    return s.sort_index()


def fetch_stooq_series(symbol):
    """Stooq 日线收盘价序列（CI 环境可用）。"""
    txt = requests.get(f"https://stooq.com/q/d/l/?s={symbol}&i=d", timeout=40).text
    s = pd.read_csv(io.StringIO(txt), sep=r"\s+")
    s.columns = [c.lower() for c in s.columns]
    s["date"] = pd.to_datetime(s["date"])
    return s.set_index("date")["close"].astype(float).sort_index()


def _try_sources(name, specs):
    """依次尝试多个源，返回首个成功的 Series；全失败抛错。specs: [(label, callable), ...]"""
    last = None
    for label, fn in specs:
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"[warn] {label} 获取 {name} 失败：{e}", file=sys.stderr)
    raise SystemExit(f"[ERROR] 所有源均无法获取 {name}：{last}")


def fetch_usdcny():
    """USD/CNY：Yahoo USDCNY=X → Stooq usdcny → FRED DEXCHUS（偶有数日延迟）。"""
    return _try_sources("USD/CNY", [
        ("Yahoo", lambda: fetch_yahoo_series("USDCNY=X")),
        ("Stooq", lambda: fetch_stooq_series("usdcny")),
        ("FRED",  lambda: fetch_fred("DEXCHUS")),
    ]).rename("usdcny")


def fetch_dxy():
    """美元指数：Yahoo DX-Y.NYB → Stooq dxy → FRED DTWEXBGS。"""
    return _try_sources("美元指数", [
        ("Yahoo", lambda: fetch_yahoo_series("DX-Y.NYB")),
        ("Stooq", lambda: fetch_stooq_series("dxy")),
        ("FRED",  lambda: fetch_fred("DTWEXBGS")),
    ]).rename("dxy")


def fetch_intl_gold():
    """国际金价（USD/oz）。优先复用 predictor 已抓取的 gold_history.csv（含最新交易日）；
    若文件缺失则按 TD_KEY→Yahoo→Stooq 兜底拉取。返回 (Series, err_or_None)。"""
    if os.path.exists(GOLD_HISTORY):
        df = (pd.read_csv(GOLD_HISTORY, parse_dates=["date"])
              .set_index("date")[["close"]].rename(columns={"close": "intl_gold"}))
        return df["intl_gold"].sort_index(), None

    # 兜底：直接拉取国际金价
    key = os.getenv("TD_KEY") or os.getenv("TWELVEDATA_KEY")
    if key:
        try:
            url = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD"
                   f"&interval=1day&outputsize=4000&apikey={key}")
            j = requests.get(url, timeout=40).json()
            if "values" in j:
                d = pd.DataFrame(j["values"])
                d["date"] = pd.to_datetime(d["datetime"])
                d["gold"] = d["close"].astype(float)
                return d.set_index("date")["gold"].sort_index(), None
        except Exception as e:
            print("[warn] Twelvedata 国际金价失败：", e, file=sys.stderr)
    try:
        import datetime as dt
        j = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
                         "?interval=1d&range=5y", timeout=40,
                         headers={"User-Agent": "Mozilla/5.0"}).json()
        r = j["chart"]["result"][0]
        ts = r["timestamp"]
        q = r["indicators"]["quote"][0]["close"]
        s = pd.Series(q, index=pd.to_datetime(ts, unit="s")).dropna()
        return s.sort_index(), None
    except Exception as e:
        print("[warn] Yahoo 国际金价失败：", e, file=sys.stderr)
    try:
        txt = requests.get("https://stooq.com/q/d/l/?s=xauusd&i=d", timeout=40).text
        s = pd.read_csv(io.StringIO(txt), sep=r"\s+")
        s.columns = [c.lower() for c in s.columns]
        s["date"] = pd.to_datetime(s["date"])
        return s.set_index("date")["close"].astype(float).sort_index(), None
    except Exception as e:
        return None, e


def main():
    # 1) 国际金价（predictor 已在 CI 中先跑，含最新交易日）
    intl, err = fetch_intl_gold()
    if intl is None:
        raise SystemExit(f"[ERROR] 无法获取国际金价（沪金依赖项）：{err}")
    intl.name = "intl_gold"

    # 2) USD/CNY（Yahoo 优先，回退 FRED DEXCHUS）
    try:
        usdcny = fetch_usdcny()
    except Exception as e:
        raise SystemExit(f"[ERROR] 无法获取 USD/CNY：{e}")

    # 3) 沪金价格（Sina，失败则后续用恒等式推导补齐）
    sg, sg_err = fetch_shgold_sina()
    if sg is None:
        print("[warn] Sina AU0 抓取失败，将用恒等式推导最新交易日：", sg_err, file=sys.stderr)
        sg = pd.DataFrame(columns=["date", "shgold"])

    # 4) 全球宏观（dxy 走 Yahoo→FRED 兜底，其余走 FRED）
    try:
        frames = [fetch_fred(sid).rename(name)
                  for name, sid in FRED_SERIES.items() if name != "dxy"]
        frames.append(fetch_dxy())
        macro = pd.concat(frames, axis=1, sort=False)
    except Exception as e:
        raise SystemExit(f"[ERROR] 无法获取宏观因子：{e}")

    # 5) 组装日期并集
    alldates = (intl.index.union(usdcny.index).union(macro.index)
                .union(sg["date"] if len(sg) else pd.DatetimeIndex([])))
    alldates = alldates.sort_values()

    shgold_full = (sg.set_index("date")["shgold"].reindex(alldates)
                   if len(sg) else pd.Series(dtype=float, index=alldates))

    # 6) 用恒等式补齐 Sina 缺失的最新交易日：
    #    shgold ≈ intl_gold * usdcny / 31.1035 + 上一已知溢价
    if len(sg):
        last_premium = (sg.set_index("date")["shgold"].iloc[-1]
                        - intl.reindex(sg["date"]).iloc[-1]
                        * usdcny.reindex(sg["date"]).iloc[-1] / 31.1035)
        tail = alldates[alldates > sg["date"].iloc[-1]]
    else:
        # Sina 完全失败：用既有文件最后溢价（若有），否则 0
        last_premium = 0.0
        tail = alldates
    if len(tail):
        deriv = (intl.reindex(tail) * usdcny.reindex(tail) / 31.1035 + last_premium)
        shgold_full = shgold_full.fillna(deriv)

    df = pd.DataFrame(index=alldates)
    df["shgold"] = shgold_full
    df["usdcny"] = usdcny.reindex(alldates)
    df["intl_gold"] = intl.reindex(alldates)
    for c in macro.columns:
        df[c] = macro[c].reindex(alldates)
    df["premium"] = df["shgold"] - df["intl_gold"] * df["usdcny"] / 31.1035
    # FRED 的 USD/CNY(DEXCHUS) 与 美元指数(DTWEXBGS) 往往晚数日才发布；
    # 前向填充后再剔除仍缺失的行，避免整段因子表被截断到滞后源的最后一天。
    df = df.ffill().dropna()
    # 统一索引为自然日（去掉任何来源的时分秒），并去除重复交易日
    df.index = df.index.normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()

    # 7) 与既有文件按日期合并，保留完整历史、用新数据覆盖重叠日
    out = os.path.join(DATA, "shgold_factors.csv")
    if os.path.exists(out):
        old = pd.read_csv(out, index_col=0, parse_dates=True)
        merged = pd.concat([old, df]).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]  # 重叠日留新
        df = merged
    df.index.name = "date"

    os.makedirs(DATA, exist_ok=True)
    df.to_csv(out, index_label="date")
    print("写入", out, "rows =", len(df),
          "range", df.index.min().date(), "->", df.index.max().date())


if __name__ == "__main__":
    main()
