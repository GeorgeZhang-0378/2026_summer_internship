#!/usr/bin/env python3
"""
fetch_shgold.py — 拉取沪金预测所需因子时序。

数据源（均无需 API key，已验证沙箱可达）：
  - 沪金价格：Sina 期货行情 AU0（SHFE 黄金主力连续），日线，2008 起。
  - USD/CNY：FRED DEXCHUS（免 key）。
  - 国际金价（USD/oz）：复用 ../predictor/data/gold_history.csv（美国黄金原型已抓取的历史）。
  - 全球宏观因子（同源美国模型）：FRED DFII10/NASDAQCOM/VIXCLS/DTWEXBGS/GVZCLS

核心恒等式：沪金(元/克) ≈ 国际金价(USD/oz) × USD/CNY ÷ 31.1035(克/盎司) + 国内溢价
  => 国际金价收益率、ΔUSD/CNY、国内溢价 是沪金最主要的三类驱动；外加全球宏观（实际利率/美元/VIX/GVZ）。

产出：data/shgold_factors.csv（原始拼接，特征在 train_shgold.py 统一构造）。
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
    "dxy": "DTWEXBGS",         # 贸易加权美元指数（广义）
    "gvz": "GVZCLS",           # CBOE 黄金隐含波动率
}


def fetch_shgold_sina(symbol=SYMBOL):
    r = requests.get(SINA_URL, timeout=25,
                     headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
    r.raise_for_status()
    rows = r.json()  # list of dicts: d,o,h,l,c,v,p
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["d"])
    df["close"] = df["c"].astype(float)
    return df[["date", "close"]].rename(columns={"close": "shgold"}).sort_values("date")


def fetch_fred(series_id, start=START):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    s = pd.read_csv(io.StringIO(r.text), skiprows=1)
    s.columns = ["date", series_id]
    s["date"] = pd.to_datetime(s["date"])
    return s.set_index("date")[series_id].astype(float)


def main():
    sg = fetch_shgold_sina().set_index("date")
    usdcny = fetch_fred("DEXCHUS").rename("usdcny")
    intl = pd.read_csv(GOLD_HISTORY, parse_dates=["date"]).set_index("date")[["close"]].rename(columns={"close": "intl_gold"})
    macro = pd.concat([fetch_fred(sid).rename(name) for name, sid in FRED_SERIES.items()], axis=1)

    df = pd.concat([sg, usdcny, intl, macro], axis=1).sort_index()
    # 国内溢价(元/克) = 沪金 - 国际金价(USD/oz) * USD/CNY / 31.1035
    df["premium"] = df["shgold"] - df["intl_gold"] * df["usdcny"] / 31.1035
    df = df.dropna()

    os.makedirs(DATA, exist_ok=True)
    out = os.path.join(DATA, "shgold_factors.csv")
    df.to_csv(out)
    print("写入", out, "rows =", len(df), "range", df.index.min().date(), "->", df.index.max().date())


if __name__ == "__main__":
    main()
