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

FAMILY = "cftc_managed_money"


def build_features(df, market):
    if "cftc_mm_net" not in df.columns:
        return {}
    net = pd.to_numeric(df["cftc_mm_net"], errors="coerce")
    out = {
        "cftc_net": net,
        "cftc_net_change4w": net - net.shift(20),
        "cftc_net_z252": rolling_zscore(net, 252, 80),
    }
    if "cftc_open_interest" in df.columns:
        oi = pd.to_numeric(df["cftc_open_interest"], errors="coerce")
        out["cftc_net_share_oi"] = net / oi.replace(0, np.nan)
    return out


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
