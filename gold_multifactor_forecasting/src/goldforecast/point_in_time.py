from __future__ import annotations
import pandas as pd


def merge_asof_available(
    base: pd.DataFrame,
    external: pd.DataFrame,
    value_columns: list[str],
    available_col: str = "available_date",
) -> pd.DataFrame:
    left = base.sort_values("date").copy()
    right = external.copy()
    right[available_col] = pd.to_datetime(right[available_col])
    right = right.sort_values(available_col)

    cols = [available_col] + value_columns
    return pd.merge_asof(
        left,
        right[cols],
        left_on="date",
        right_on=available_col,
        direction="backward",
    ).drop(columns=[available_col])
