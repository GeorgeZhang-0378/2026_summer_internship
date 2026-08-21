import numpy as np
import pandas as pd

from goldforecast.walkforward import run_univariate_factor


def test_walkforward_smoke():
    rng = np.random.default_rng(123)
    n = 1200
    dates = pd.bdate_range("2015-01-01", periods=n)
    r = 0.0002 + 0.01 * rng.standard_normal(n)
    close = 1200 * np.exp(np.cumsum(r))
    df = pd.DataFrame({"date": dates, "close": close})
    feature = pd.Series(r).rolling(20, min_periods=10).sum()

    summary, oos = run_univariate_factor(
        df=df,
        feature=feature,
        market="london",
        family="smoke",
        feature_name="rolling_return",
        horizon=20,
        min_train=504,
        test_size=63,
    )

    assert summary.n_folds > 0
    assert len(oos) > 0
    assert 0 <= summary.coverage <= 1
