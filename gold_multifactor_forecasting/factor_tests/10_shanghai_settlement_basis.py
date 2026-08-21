from pathlib import Path
import argparse
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goldforecast.data import load_model_data
from goldforecast.feature_utils import log_return, pct_change, rolling_zscore, safe_ratio
from goldforecast.walkforward import run_feature_dict

FAMILY = "shanghai_settlement_basis"


def build_features(df, market):
    if market != "shanghai" or "settlement" not in df.columns:
        return {}
    s = pd.to_numeric(df["settlement"], errors="coerce")
    c = pd.to_numeric(df["close"], errors="coerce")
    basis = s / c.replace(0, np.nan) - 1
    return {
        "settlement_close_basis": basis,
        "basis_z60": rolling_zscore(basis, 60, 20),
        "basis_change5": basis - basis.shift(5),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["london", "shanghai"], required=True)
    p.add_argument("--horizon", type=int, default=20)
    args = p.parse_args()

    df = load_model_data(args.market)
    features = build_features(df, args.market)
    run_feature_dict(
        df=df,
        features=features,
        market=args.market,
        family=FAMILY,
        horizon=args.horizon,
        output_dir=ROOT / "results" / "factor_tests",
    )


if __name__ == "__main__":
    main()
