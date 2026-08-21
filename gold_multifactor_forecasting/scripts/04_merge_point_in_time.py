from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
EXTERNAL = ROOT / "data" / "external"


def merge_one(base, file_name, value_cols):
    path = EXTERNAL / file_name
    if not path.exists():
        return base
    ext = pd.read_csv(path, parse_dates=["available_date"])
    ext = ext.sort_values("available_date")
    return pd.merge_asof(
        base.sort_values("date"),
        ext[["available_date"] + value_cols],
        left_on="date",
        right_on="available_date",
        direction="backward",
    ).drop(columns="available_date")


def add_external(base):
    mapping = [
        ("real_yield_10y.csv", ["real_yield_10y"]),
        ("yield_2y.csv", ["yield_2y"]),
        ("yield_10y.csv", ["yield_10y"]),
        ("breakeven_10y.csv", ["breakeven_10y"]),
        ("broad_usd.csv", ["broad_usd"]),
        ("vix.csv", ["vix"]),
        ("hy_oas.csv", ["hy_oas"]),
        ("usd_cny.csv", ["usd_cny"]),
        ("cftc_gold_managed_money.csv",
         ["cftc_mm_long", "cftc_mm_short", "cftc_mm_net", "cftc_open_interest"]),
    ]
    out = base
    for file_name, cols in mapping:
        path = EXTERNAL / file_name
        if path.exists():
            existing = pd.read_csv(path, nrows=1).columns
            cols = [c for c in cols if c in existing]
            out = merge_one(out, file_name, cols)
    return out


def build():
    london = pd.read_csv(PROCESSED / "london_base.csv", parse_dates=["date"]).sort_values("date")
    shanghai = pd.read_csv(PROCESSED / "shanghai_base.csv", parse_dates=["date"]).sort_values("date")

    london = add_external(london)
    shanghai = add_external(shanghai)

    # Conservative cross-market data: previous available close only.
    lref = london[["date", "close"]].rename(columns={"close": "london_close_ref"})
    lref["date"] = lref["date"] + pd.Timedelta(days=1)
    shanghai = pd.merge_asof(
        shanghai.sort_values("date"),
        lref.sort_values("date"),
        on="date",
        direction="backward",
    )

    sref = shanghai[["date", "close"]].rename(columns={"close": "shanghai_close_ref"})
    sref["date"] = sref["date"] + pd.Timedelta(days=1)
    london = pd.merge_asof(
        london.sort_values("date"),
        sref.sort_values("date"),
        on="date",
        direction="backward",
    )

    # Shanghai-vs-London premium/basis using only previously available London close.
    if {"london_close_ref", "usd_cny"}.issubset(shanghai.columns):
        london_rmb_per_g = shanghai["london_close_ref"] * shanghai["usd_cny"] / 31.1034768
        shanghai["shanghai_london_premium"] = shanghai["close"] / london_rmb_per_g - 1.0

    london.to_csv(PROCESSED / "london_model.csv", index=False)
    shanghai.to_csv(PROCESSED / "shanghai_model.csv", index=False)
    print("Wrote london_model.csv and shanghai_model.csv")


if __name__ == "__main__":
    build()
