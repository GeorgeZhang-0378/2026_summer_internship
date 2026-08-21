from __future__ import annotations
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .targets import add_targets


@dataclass
class FactorSummary:
    market: str
    family: str
    feature: str
    horizon: int
    n_oos: int
    n_folds: int
    coverage: float
    ic: float | None
    auc: float | None
    accuracy: float | None
    balanced_accuracy: float | None
    brier: float | None
    sign_consistency: float | None
    mean_fold_ic: float | None
    median_fold_ic: float | None


def _ic(x, y):
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 10:
        return np.nan
    v = spearmanr(np.asarray(x)[mask], np.asarray(y)[mask]).statistic
    return float(v) if np.isfinite(v) else np.nan


def _auc(y, p):
    if len(np.unique(y)) < 2:
        return np.nan
    return float(roc_auc_score(y, p))


def run_univariate_factor(
    df: pd.DataFrame,
    feature: pd.Series,
    market: str,
    family: str,
    feature_name: str,
    horizon: int = 20,
    embargo: int = 5,
    min_train: int = 756,
    test_size: int = 63,
    rolling_train: int | None = None,
):
    work = add_targets(df, horizon).copy()
    work["feature"] = pd.to_numeric(feature, errors="coerce")

    ret_col = f"future_log_return_{horizon}d"
    up_col = f"up_{horizon}d"
    coverage = float(work["feature"].notna().mean())

    folds = []
    fold_ics = []
    coef_signs = []
    fold_id = 0

    # First test starts only after enough history PLUS the purged/embargo gap.
    test_start = min_train + horizon + embargo
    n = len(work)

    while test_start < n - horizon:
        test_end = min(test_start + test_size, n - horizon)
        train_end = test_start - horizon - embargo
        train_start = 0 if rolling_train is None else max(0, train_end - rolling_train)

        train = work.iloc[train_start:train_end].dropna(subset=["feature", ret_col, up_col])
        test = work.iloc[test_start:test_end].dropna(subset=["feature", ret_col, up_col])

        if len(train) >= max(100, min_train // 3) and len(test) >= 10 and train[up_col].nunique() == 2:
            pipe = Pipeline([
                ("scaler", StandardScaler()),
                ("model", LogisticRegression(
                    C=0.5,
                    solver="lbfgs",
                    class_weight="balanced",
                    max_iter=2000,
                )),
            ])

            pipe.fit(train[["feature"]], train[up_col].astype(int))
            p = pipe.predict_proba(test[["feature"]])[:, 1]
            coef = float(pipe.named_steps["model"].coef_[0, 0])

            tmp = test[["date", "feature", ret_col, up_col]].copy()
            tmp["p_up"] = p
            tmp["fold"] = fold_id
            tmp["coefficient"] = coef
            folds.append(tmp)

            fold_ics.append(_ic(tmp["feature"].to_numpy(), tmp[ret_col].to_numpy()))
            coef_signs.append(np.sign(coef))
            fold_id += 1

        test_start += test_size

    if not folds:
        summary = FactorSummary(
            market, family, feature_name, horizon, 0, 0, coverage,
            None, None, None, None, None, None, None, None
        )
        return summary, pd.DataFrame()

    oos = pd.concat(folds, ignore_index=True)
    y = oos[up_col].astype(int).to_numpy()
    p = oos["p_up"].to_numpy()
    pred = (p >= 0.5).astype(int)

    signs = np.array([s for s in coef_signs if s != 0], dtype=float)
    if len(signs):
        majority = np.sign(signs.sum())
        sign_consistency = float(np.mean(signs == majority)) if majority != 0 else 0.5
    else:
        sign_consistency = np.nan

    valid_ic = np.array([x for x in fold_ics if np.isfinite(x)], dtype=float)
    total_ic = _ic(oos["feature"].to_numpy(), oos[ret_col].to_numpy())

    summary = FactorSummary(
        market=market,
        family=family,
        feature=feature_name,
        horizon=horizon,
        n_oos=len(oos),
        n_folds=fold_id,
        coverage=coverage,
        ic=float(total_ic) if np.isfinite(total_ic) else None,
        auc=_auc(y, p) if np.isfinite(_auc(y, p)) else None,
        accuracy=float(accuracy_score(y, pred)),
        balanced_accuracy=float(balanced_accuracy_score(y, pred)),
        brier=float(brier_score_loss(y, p)),
        sign_consistency=float(sign_consistency) if np.isfinite(sign_consistency) else None,
        mean_fold_ic=float(valid_ic.mean()) if len(valid_ic) else None,
        median_fold_ic=float(np.median(valid_ic)) if len(valid_ic) else None,
    )
    return summary, oos


def save_factor_result(summary, oos, output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{summary.market}__{summary.family}__{summary.feature}__{summary.horizon}d".replace("/", "_")
    (out / f"{stem}.json").write_text(
        json.dumps(asdict(summary), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if not oos.empty and os.getenv("GOLD_SAVE_OOS", "0") == "1":
        oos.to_csv(out / f"{stem}_oos.csv", index=False)


def run_feature_dict(df, features, market, family, horizon, output_dir):
    if not features:
        print(f"[SKIP] {family}: required columns unavailable for {market}.")
        return

    for name, feature in features.items():
        summary, oos = run_univariate_factor(
            df=df,
            feature=feature,
            market=market,
            family=family,
            feature_name=name,
            horizon=horizon,
        )
        save_factor_result(summary, oos, output_dir)
        print(
            f"{market:8s} | {family:26s} | {name:28s} "
            f"| folds={summary.n_folds:2d} "
            f"| IC={summary.ic} | AUC={summary.auc} | Brier={summary.brier}"
        )
