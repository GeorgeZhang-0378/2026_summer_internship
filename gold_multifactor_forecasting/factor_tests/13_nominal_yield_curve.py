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

FAMILY = "nominal_yield_curve"


def build_features(df, market):
    if not {"yield_2y", "yield_10y"}.issubset(df.columns):
        return {}
    y2 = pd.to_numeric(df["yield_2y"], errors="coerce")
    y10 = pd.to_numeric(df["yield_10y"], errors="coerce")
    curve = y10 - y2
    return {
        "yield2_change20": y2 - y2.shift(20),
        "yield10_change20": y10 - y10.shift(20),
        "curve_10y_2y": curve,
        "curve_change20": curve - curve.shift(20),
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
