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

FAMILY = "gold_etf_flows"


def build_features(df, market):
    # Optional factor. Add a point-in-time `gold_etf_flow` column to the merged dataset.
    if "gold_etf_flow" not in df.columns:
        return {}
    x = pd.to_numeric(df["gold_etf_flow"], errors="coerce")
    return {
        "etf_flow_raw": x,
        "etf_flow_sum20": x.rolling(20, min_periods=5).sum(),
        "etf_flow_z252": rolling_zscore(x, 252, 80),
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
