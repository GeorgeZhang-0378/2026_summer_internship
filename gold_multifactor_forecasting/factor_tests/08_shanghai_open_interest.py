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

FAMILY = "shanghai_open_interest"


def build_features(df, market):
    if market != "shanghai" or "open_interest" not in df.columns:
        return {}
    x = pd.to_numeric(df["open_interest"], errors="coerce")
    return {
        "oi_z60": rolling_zscore(np.log1p(x), 60, 20),
        "oi_change5": x / x.shift(5) - 1,
        "oi_change20": x / x.shift(20) - 1,
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
