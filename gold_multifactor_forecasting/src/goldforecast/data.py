from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def load_base(market: str) -> pd.DataFrame:
    market = market.lower()
    if market not in {"london", "shanghai"}:
        raise ValueError("market must be 'london' or 'shanghai'")
    path = ROOT / "data" / "processed" / f"{market}_base.csv"
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def load_model_data(market: str) -> pd.DataFrame:
    market = market.lower()
    path = ROOT / "data" / "processed" / f"{market}_model.csv"
    if not path.exists():
        return load_base(market)
    df = pd.read_csv(path, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    # Default research sample avoids treating the pre-modern gold market as directly comparable.
    if market == "london":
        df = df[df["date"] >= pd.Timestamp("1980-01-01")].reset_index(drop=True)
    return df
