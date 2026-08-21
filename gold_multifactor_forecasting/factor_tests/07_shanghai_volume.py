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

FAMILY = "shanghai_volume"


def build_features(df, market):
    if market != "shanghai" or "volume" not in df.columns:
        return {}
    v = pd.to_numeric(df["volume"], errors="coerce")
    return {
        "volume_z60": rolling_zscore(np.log1p(v), 60, 20),
        "volume_change20": v / v.shift(20) - 1,
        "volume_ma20_ma60": v.rolling(20, min_periods=10).mean() / v.rolling(60, min_periods=20).mean() - 1,
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
