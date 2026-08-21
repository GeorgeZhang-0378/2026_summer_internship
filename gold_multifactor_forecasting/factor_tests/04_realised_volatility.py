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

FAMILY = "realised_volatility"


def build_features(df, market):
    r = log_return(df["close"], 1)
    rv20 = r.rolling(20, min_periods=10).std(ddof=0) * np.sqrt(252)
    rv60 = r.rolling(60, min_periods=20).std(ddof=0) * np.sqrt(252)
    rv252 = r.rolling(252, min_periods=80).std(ddof=0) * np.sqrt(252)
    return {
        "rv20": rv20,
        "rv60": rv60,
        "rv252": rv252,
        "rv20_over_rv60": rv20 / rv60.replace(0, np.nan),
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
