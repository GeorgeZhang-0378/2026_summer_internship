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

FAMILY = "seasonality"


def build_features(df, market):
    d = pd.to_datetime(df["date"])
    month = d.dt.month.astype(float)
    dow = d.dt.dayofweek.astype(float)
    doy = d.dt.dayofyear.astype(float)
    return {
        "month_sin": np.sin(2*np.pi*month/12),
        "month_cos": np.cos(2*np.pi*month/12),
        "dow_sin": np.sin(2*np.pi*dow/5),
        "dow_cos": np.cos(2*np.pi*dow/5),
        "annual_sin": np.sin(2*np.pi*doy/365.25),
        "annual_cos": np.cos(2*np.pi*doy/365.25),
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
