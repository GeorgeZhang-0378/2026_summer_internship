#!/usr/bin/env python3
"""生成 data/macro_history.json：把主模型用到的宏观因子（FRED 免key + WGC 央行净购金）
预拉取为一份日线历史，随站点发布。上传即预测模块训练时按日期本地 JOIN，不再联网。
因子：real_rate(DFII10), spx(NASDAQCOM), vix(VIXCLS), dxy(DTWEXBGS), gvz(GVZCLS), cb_net(WGC)。
派生：spx_ret_252, dxy_chg_252（与主模型特征语义一致）。
"""
import csv, json, os, subprocess, datetime, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "macro_history.json")
CB_CSV = os.path.join(HERE, "data", "cb_gold.csv")
START = "2000-01-01"

FRED = {
    "real_rate": "DFII10",
    "spx": "NASDAQCOM",
    "vix": "VIXCLS",
    "dxy": "DTWEXBGS",
    "gvz": "GVZCLS",
}

def fetch_fred(sid):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={START}"
    out = subprocess.run(["curl", "-s", url], capture_output=True, text=True).stdout
    data = {}
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or "," not in line:
            continue
        d, v = line.split(",", 1)
        d = d.strip()
        try:
            data[d] = float(v)
        except ValueError:
            data[d] = None
    return data

def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += datetime.timedelta(days=1)

def main():
    print("拉取 FRED 因子…")
    series = {name: fetch_fred(sid) for name, sid in FRED.items()}

    # WGC 央行净购金：year -> net_tonnes；按"上一年值、无前视"映射到每日
    cb = {}
    with open(CB_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cb[int(row["year"])] = float(row["net_tonnes"])
    years = sorted(cb.keys())

    start = datetime.date(2000, 1, 1)
    end = datetime.date.today()
    # 建立连续日序列，逐序列前向填充
    filled = {name: {} for name in FRED}
    last = {name: None for name in FRED}
    for d in daterange(start, end):
        ds = d.isoformat()
        for name in FRED:
            v = series[name].get(ds)
            if v is not None and v == v:  # 非 NaN
                last[name] = v
            filled[name][ds] = last[name]

    # 派生 spx_ret_252 / dxy_chg_252 需 252 个交易日前的 spx/dxy（用日历日近似）
    spx_list = [(ds, filled["spx"][ds]) for ds in (x.isoformat() for x in daterange(start, end))]
    dxy_list = [(ds, filled["dxy"][ds]) for ds in (x.isoformat() for x in daterange(start, end))]

    def rnd(v, n):
        return None if v is None else round(v, n)

    records = []
    all_dates = [d.isoformat() for d in daterange(start, end)]
    for i, ds in enumerate(all_dates):
        # 央行净购金：取该日期所在年份的"上一年"净购（无前视）
        y = int(ds[:4])
        prev = y - 1
        cb_val = cb.get(prev)
        if cb_val is None:  # 早于最早年份则取最早
            cb_val = cb.get(years[0])
        spx = filled["spx"][ds]
        dxy = filled["dxy"][ds]
        spx_ret = None
        dxy_chg = None
        if i >= 252 and spx is not None and spx_list[i - 252][1] not in (None, 0):
            spx_ret = spx / spx_list[i - 252][1] - 1
        if i >= 252 and dxy is not None and dxy_list[i - 252][1] not in (None, 0):
            dxy_chg = dxy / dxy_list[i - 252][1] - 1
        records.append({
            "date": ds,
            "real_rate": rnd(filled["real_rate"][ds], 3),
            "spx_ret_252": rnd(spx_ret, 5),
            "vix": rnd(filled["vix"][ds], 2),
            "dxy_chg_252": rnd(dxy_chg, 5),
            "gvz": rnd(filled["gvz"][ds], 2),
            "cb_net": rnd(cb_val, 1),
        })

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(records, f, separators=(",", ":"))
    print(f"写入 {OUT}  共 {len(records)} 行  ({records[0]['date']} ~ {records[-1]['date']})")

if __name__ == "__main__":
    main()
