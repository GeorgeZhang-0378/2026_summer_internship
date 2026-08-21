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

FAMILY = "trend_strength"


def build_features(df, market):
    px = pd.to_numeric(df["close"], errors="coerce")
    ma20 = px.rolling(20, min_periods=10).mean()
    ma60 = px.rolling(60, min_periods=20).mean()
    hi60 = px.rolling(60, min_periods=20).max()
    lo60 = px.rolling(60, min_periods=20).min()
    return {
        "close_ma20_gap": px / ma20 - 1,
        "ma20_ma60_gap": ma20 / ma60 - 1,
        "breakout_60": (px - lo60) / (hi60 - lo60).replace(0, np.nan) - 0.5,
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
