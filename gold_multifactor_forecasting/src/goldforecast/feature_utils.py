from __future__ import annotations
import numpy as np
import pandas as pd


def log_return(s: pd.Series, periods: int = 1) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    return np.log(x / x.shift(periods))


def pct_change(s: pd.Series, periods: int = 1) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").pct_change(periods=periods, fill_method=None)


def rolling_zscore(s: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    min_periods = min_periods or max(20, window // 3)
    mu = x.rolling(window, min_periods=min_periods).mean()
    sd = x.rolling(window, min_periods=min_periods).std(ddof=0)
    return (x - mu) / sd.replace(0, np.nan)


def safe_ratio(a: pd.Series, b: pd.Series) -> pd.Series:
    aa = pd.to_numeric(a, errors="coerce")
    bb = pd.to_numeric(b, errors="coerce")
    return aa / bb.replace(0, np.nan)
