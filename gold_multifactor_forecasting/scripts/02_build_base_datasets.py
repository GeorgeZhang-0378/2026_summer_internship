"""
Rebuild normalized CSV files from the two Wind Excel files.

The downloadable project already contains normalized CSVs.
This script is provided so the transformation is reproducible.
"""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)


def _excel_date(series):
    # Wind export stores Excel serial dates in the supplied files.
    return pd.Timestamp("1899-12-30") + pd.to_timedelta(pd.to_numeric(series), unit="D")


def build_london():
    path = RAW / "london_gold_spot.xlsx"
    df = pd.read_excel(path, sheet_name="file")
    df = df[df["代码"].eq("SPTAUUSDOZ.IDC")].copy()
    out = pd.DataFrame({
        "date": _excel_date(df["日期"]),
        "code": df["代码"],
        "name": df["名称"],
        "open": pd.to_numeric(df["开盘价(元)"], errors="coerce"),
        "high": pd.to_numeric(df["最高价(元)"], errors="coerce"),
        "low": pd.to_numeric(df["最低价(元)"], errors="coerce"),
        "close": pd.to_numeric(df["收盘价(元)"], errors="coerce"),
        "vendor_return": pd.to_numeric(df["涨跌幅"], errors="coerce"),
        "turnover_million": pd.to_numeric(df["成交额(百万)"], errors="coerce"),
        "volume": pd.to_numeric(df["成交量(股)"], errors="coerce"),
    })
    out.to_csv(OUT / "london_base.csv", index=False)


def build_shanghai():
    path = RAW / "shanghai_gold_AU_SHF.xlsx"
    df = pd.read_excel(path, sheet_name="file")
    df = df[df["代码"].eq("AU.SHF")].copy()
    out = pd.DataFrame({
        "date": _excel_date(df["日期"]),
        "code": df["代码"],
        "name": df["名称"],
        "open": pd.to_numeric(df["开盘价(元)"], errors="coerce"),
        "high": pd.to_numeric(df["最高价(元)"], errors="coerce"),
        "low": pd.to_numeric(df["最低价(元)"], errors="coerce"),
        "close": pd.to_numeric(df["收盘价(元)"], errors="coerce"),
        "settlement": pd.to_numeric(df["结算价"], errors="coerce"),
        "vendor_return": pd.to_numeric(df["涨跌幅"], errors="coerce"),
        "turnover_million": pd.to_numeric(df["成交额(百万)"], errors="coerce"),
        "volume": pd.to_numeric(df["成交量"], errors="coerce"),
        "open_interest": pd.to_numeric(df["持仓量"], errors="coerce"),
    })
    out.to_csv(OUT / "shanghai_base.csv", index=False)


if __name__ == "__main__":
    build_london()
    build_shanghai()
    print("Rebuilt London and Shanghai normalized base datasets.")
