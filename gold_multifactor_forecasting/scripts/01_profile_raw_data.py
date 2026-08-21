from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

for market in ["london", "shanghai"]:
    path = ROOT / "data" / "processed" / f"{market}_base.csv"
    df = pd.read_csv(path, parse_dates=["date"])
    print("=" * 80)
    print(market.upper())
    print("rows:", len(df))
    print("date range:", df["date"].min().date(), "->", df["date"].max().date())
    print("columns:", list(df.columns))
    print("missing:")
    print(df.isna().sum().to_string())
