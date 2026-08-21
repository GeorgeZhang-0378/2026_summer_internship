from __future__ import annotations
import numpy as np
import pandas as pd


def add_targets(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    out = df.copy()
    px = pd.to_numeric(out["close"], errors="coerce")
    out[f"future_log_return_{horizon}d"] = np.log(px.shift(-horizon) / px)
    out[f"up_{horizon}d"] = (out[f"future_log_return_{horizon}d"] > 0).astype(float)
    out.loc[out[f"future_log_return_{horizon}d"].isna(), f"up_{horizon}d"] = np.nan
    return out
