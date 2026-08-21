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

FAMILY = "cross_market_lead_lag"


def build_features(df, market):
    if market == "shanghai" and "london_close_ref" in df.columns:
        x = pd.to_numeric(df["london_close_ref"], errors="coerce")
        return {
            "london_ref_ret1": log_return(x, 1),
            "london_ref_ret5": log_return(x, 5),
            "london_ref_ret20": log_return(x, 20),
        }
    if market == "london" and "shanghai_close_ref" in df.columns:
        x = pd.to_numeric(df["shanghai_close_ref"], errors="coerce")
        return {
            "shanghai_ref_ret1": log_return(x, 1),
            "shanghai_ref_ret5": log_return(x, 5),
            "shanghai_ref_ret20": log_return(x, 20),
        }
    return {}


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
