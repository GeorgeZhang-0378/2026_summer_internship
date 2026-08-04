#!/usr/bin/env python3
"""Interactive historical-pattern finder for Chinese gold-price workbooks.

The program reads an Excel/CSV time series, lets the user choose a reference
window and a historical search range, ranks non-overlapping analog windows,
and writes charts plus CSV files.  Similarity is computed from scale-free,
per-window normalized trajectories; it is an exploratory scenario tool, not
an investment forecast.
"""

from __future__ import annotations

import math
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def _load_dependencies():
    try:
        import numpy as np
        import pandas as pd

        # Use a writable cache without changing an explicitly configured location.
        os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "gold-pattern-matplotlib"))
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib import font_manager
    except ImportError as exc:
        missing = getattr(exc, "name", "a required package")
        print(f"Missing Python package: {missing}")
        print("Install dependencies with:")
        print("  python3 -m pip install pandas numpy matplotlib openpyxl")
        raise SystemExit(1) from exc
    return np, pd, plt, mdates, font_manager


np, pd, plt, mdates, font_manager = _load_dependencies()


DATE_COLUMN = "日期"
PRICE_COLUMNS = ["开盘价(元)", "最高价(元)", "最低价(元)", "收盘价(元)"]
OTHER_COLUMNS = ["涨跌幅", "成交额(百万)", "成交量(股)"]
FEATURE_COLUMNS = PRICE_COLUMNS + OTHER_COLUMNS
ENGLISH_NAMES = {
    "开盘价(元)": "Open",
    "最高价(元)": "High",
    "最低价(元)": "Low",
    "收盘价(元)": "Close",
    "涨跌幅": "Change",
    "成交额(百万)": "Turnover",
    "成交量(股)": "Volume",
}


def say(en: str, zh: str = "") -> None:
    print(en)
    if zh:
        print(zh)


def clean_path(text: str) -> Path:
    """Accept normal paths and paths dragged into a macOS/Linux terminal."""
    text = text.strip().strip("\"'")
    text = text.replace("\\ ", " ")
    return Path(os.path.expandvars(os.path.expanduser(text))).resolve()


def configure_chinese_font() -> None:
    preferred = [
        "PingFang SC",
        "Arial Unicode MS",
        "Microsoft YaHei",
        "Noto Sans CJK SC",
        "WenQuanYi Zen Hei",
        "SimHei",
    ]
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for name in preferred:
        if name in installed:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            break
    plt.rcParams["axes.unicode_minus"] = False


def prompt_int(prompt: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            say("Please enter a whole number.", "请输入整数。")
            continue
        if value < minimum or (maximum is not None and value > maximum):
            upper = f" and at most {maximum}" if maximum is not None else ""
            say(f"Value must be at least {minimum}{upper}.", f"数值必须至少为 {minimum}{'，且不超过 '+str(maximum) if maximum is not None else ''}。")
            continue
        return value


def parse_numeric(series: "pd.Series") -> "pd.Series":
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    raw = series.astype("string").str.strip()
    percent_mask = raw.str.endswith("%", na=False)
    cleaned = (
        raw.str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.replace("—", "", regex=False)
        .str.replace("--", "", regex=False)
    )
    values = pd.to_numeric(cleaned, errors="coerce")
    values.loc[percent_mask] = values.loc[percent_mask] / 100.0
    return values


def read_input_file(path: Path) -> tuple["pd.DataFrame", str]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        book = pd.ExcelFile(path, engine="openpyxl")
        sheets = book.sheet_names
        if len(sheets) == 1:
            sheet = sheets[0]
        else:
            say("Available sheets:", "可用工作表：")
            for i, name in enumerate(sheets, 1):
                print(f"  {i}. {name}")
            choice = prompt_int("Sheet number / 工作表编号", 1, 1, len(sheets))
            sheet = sheets[choice - 1]
        frame = pd.read_excel(book, sheet_name=sheet)
        return frame, sheet
    if suffix == ".csv":
        for encoding in ("utf-8-sig", "gb18030", "utf-8"):
            try:
                return pd.read_csv(path, encoding=encoding), "CSV"
            except UnicodeDecodeError:
                continue
        raise ValueError("Could not determine the CSV encoding.")
    raise ValueError("Supported input formats are .xlsx, .xlsm, and .csv.")


def prepare_data(frame: "pd.DataFrame") -> tuple["pd.DataFrame", dict[str, int]]:
    frame = frame.copy()
    frame.columns = [re.sub(r"\s+", "", str(c)) for c in frame.columns]
    if DATE_COLUMN not in frame.columns:
        raise ValueError(f"Required date column '{DATE_COLUMN}' was not found. Columns: {list(frame.columns)}")

    available = [column for column in FEATURE_COLUMNS if column in frame.columns]
    if not available:
        raise ValueError("None of the seven expected numeric columns was found.")

    original_rows = len(frame)
    frame[DATE_COLUMN] = pd.to_datetime(frame[DATE_COLUMN], errors="coerce")
    for column in available:
        frame[column] = parse_numeric(frame[column])

    invalid_dates = int(frame[DATE_COLUMN].isna().sum())
    frame = frame.dropna(subset=[DATE_COLUMN]).sort_values(DATE_COLUMN)
    duplicate_dates = int(frame.duplicated(DATE_COLUMN, keep="last").sum())
    frame = frame.drop_duplicates(DATE_COLUMN, keep="last").reset_index(drop=True)
    stats = {
        "original_rows": original_rows,
        "invalid_dates": invalid_dates,
        "duplicate_dates": duplicate_dates,
    }
    return frame, stats


def choose_features(frame: "pd.DataFrame") -> list[str]:
    available = [column for column in FEATURE_COLUMNS if column in frame.columns]
    say("Choose the variables used for similarity matching:", "选择用于相似趋势匹配的变量：")
    print("  0. All available variables / 全部可用变量")
    for i, column in enumerate(available, 1):
        print(f"  {i}. {column} ({ENGLISH_NAMES[column]})")
    while True:
        raw = input("Selection, e.g. 4 or 1,2,3 [0] / 选择: ").strip() or "0"
        if raw == "0":
            return available
        try:
            indices = sorted({int(item.strip()) for item in raw.split(",")})
        except ValueError:
            say("Use numbers separated by commas.", "请使用逗号分隔的数字。")
            continue
        if indices and all(1 <= item <= len(available) for item in indices):
            return [available[item - 1] for item in indices]
        say("One or more selections are outside the available range.", "一个或多个选项超出可用范围。")


def prompt_date(prompt: str, default: "pd.Timestamp | None" = None) -> "pd.Timestamp | None":
    default_text = default.strftime("%Y-%m-%d") if default is not None else "blank"
    while True:
        raw = input(f"{prompt} [{default_text}]: ").strip()
        if not raw:
            return default
        try:
            return pd.Timestamp(raw).normalize()
        except Exception:
            say("Please use a recognizable date such as 2024-01-31.", "请输入可识别的日期，例如 2024-01-31。")


def snap_start(dates: "pd.Series", requested: "pd.Timestamp") -> "pd.Timestamp":
    candidates = dates[dates >= requested]
    if candidates.empty:
        raise ValueError("The requested start date is later than the final available date.")
    return pd.Timestamp(candidates.iloc[0])


def snap_end(dates: "pd.Series", requested: "pd.Timestamp") -> "pd.Timestamp":
    candidates = dates[dates <= requested]
    if candidates.empty:
        raise ValueError("The requested end date is earlier than the first available date.")
    return pd.Timestamp(candidates.iloc[-1])


def choose_reference_window(frame: "pd.DataFrame") -> tuple[int, int]:
    dates = frame[DATE_COLUMN]
    say(
        f"Usable date range: {dates.iloc[0]:%Y-%m-%d} to {dates.iloc[-1]:%Y-%m-%d} ({len(frame):,} observations).",
        f"可用日期范围：{dates.iloc[0]:%Y-%m-%d} 至 {dates.iloc[-1]:%Y-%m-%d}（{len(frame):,} 个观测值）。",
    )
    raw_start = input("Reference start date; blank = most recent observations / 目标区间开始日期（留空=最近数据）: ").strip()
    if not raw_start:
        recent = prompt_int("Number of recent observations / 最近观测值数量", 60, 3, len(frame))
        return len(frame) - recent, len(frame) - 1

    try:
        requested_start = pd.Timestamp(raw_start).normalize()
    except Exception as exc:
        raise ValueError("The reference start date could not be parsed.") from exc
    actual_start = snap_start(dates, requested_start)
    requested_end = prompt_date("Reference end date / 目标区间结束日期", dates.iloc[-1])
    actual_end = snap_end(dates, requested_end)
    if actual_end < actual_start:
        raise ValueError("Reference end date must be on or after the reference start date.")
    start_idx = int(dates.searchsorted(actual_start, side="left"))
    end_idx = int(dates.searchsorted(actual_end, side="right") - 1)
    if end_idx - start_idx + 1 < 3:
        raise ValueError("The reference window must contain at least three observations.")
    if actual_start != requested_start or actual_end != requested_end:
        say(
            f"Dates snapped to available observations: {actual_start:%Y-%m-%d} to {actual_end:%Y-%m-%d}.",
            f"日期已自动对齐到可用观测值：{actual_start:%Y-%m-%d} 至 {actual_end:%Y-%m-%d}。",
        )
    return start_idx, end_idx


def choose_search_range(frame: "pd.DataFrame", ref_start_idx: int) -> tuple["pd.Timestamp", "pd.Timestamp"]:
    dates = frame[DATE_COLUMN]
    default_end_idx = max(0, ref_start_idx - 1)
    requested_start = prompt_date("Historical search start; blank = earliest / 历史搜索开始日期（留空=最早）", dates.iloc[0])
    requested_end = prompt_date(
        "Historical search end; default = observation before reference / 历史搜索结束日期（默认=目标区间之前）",
        dates.iloc[default_end_idx],
    )
    actual_start = snap_start(dates, requested_start)
    actual_end = snap_end(dates, requested_end)
    if actual_end < actual_start:
        raise ValueError("Historical search end must be on or after its start.")
    return actual_start, actual_end


def transformed(values: "np.ndarray", column: str) -> "np.ndarray":
    values = np.asarray(values, dtype=float)
    if column in PRICE_COLUMNS:
        if np.any(values <= 0):
            raise ValueError(f"'{column}' contains a zero or negative value; log-price matching is not possible.")
        return np.log(values / values[0])
    if column in {"成交额(百万)", "成交量(股)"}:
        if np.any(values < 0):
            raise ValueError(f"'{column}' contains a negative value.")
        return np.log1p(values)
    return values


def z_normalize(values: "np.ndarray") -> "np.ndarray":
    std = float(np.std(values))
    if not math.isfinite(std) or std < 1e-12:
        return np.zeros_like(values, dtype=float)
    return (values - float(np.mean(values))) / std


def feature_comparison(reference: "np.ndarray", candidate: "np.ndarray", column: str) -> tuple[float, float]:
    ref_raw = transformed(reference, column)
    cand_raw = transformed(candidate, column)
    ref = z_normalize(ref_raw)
    cand = z_normalize(cand_raw)
    distance = float(np.sqrt(np.mean((ref - cand) ** 2)))
    ref_std = float(np.std(ref_raw))
    cand_std = float(np.std(cand_raw))
    if ref_std < 1e-12 and cand_std < 1e-12:
        correlation = 1.0
    elif ref_std < 1e-12 or cand_std < 1e-12:
        correlation = 0.0
    else:
        correlation = float(np.corrcoef(ref_raw, cand_raw)[0, 1])
    return distance, correlation


def informative_reference_features(
    frame: "pd.DataFrame", features: list[str], ref_start_idx: int, ref_end_idx: int
) -> tuple[list[str], list[str]]:
    """Remove reference features whose transformed trajectory has no variation."""
    informative: list[str] = []
    constant: list[str] = []
    reference = frame.iloc[ref_start_idx : ref_end_idx + 1]
    for column in features:
        values = reference[column].to_numpy(dtype=float)
        transformed_values = transformed(values, column)
        if float(np.std(transformed_values)) < 1e-12:
            constant.append(column)
        else:
            informative.append(column)
    return informative, constant


def windows_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return max(a_start, b_start) <= min(a_end, b_end)


def find_matches(
    frame: "pd.DataFrame",
    features: list[str],
    ref_start_idx: int,
    ref_end_idx: int,
    search_start: "pd.Timestamp",
    search_end: "pd.Timestamp",
    horizon: int,
    top_n: int,
) -> tuple["pd.DataFrame", list[dict]]:
    length = ref_end_idx - ref_start_idx + 1
    reference = frame.iloc[ref_start_idx : ref_end_idx + 1]
    candidates: list[dict] = []
    max_start = len(frame) - length

    for start_idx in range(max_start + 1):
        end_idx = start_idx + length - 1
        if frame.at[start_idx, DATE_COLUMN] < search_start or frame.at[end_idx, DATE_COLUMN] > search_end:
            continue
        if windows_overlap(start_idx, end_idx, ref_start_idx, ref_end_idx):
            continue
        if end_idx + horizon >= len(frame):
            continue

        distances: list[float] = []
        correlations: dict[str, float] = {}
        invalid = False
        for column in features:
            ref_values = reference[column].to_numpy(dtype=float)
            cand_values = frame.iloc[start_idx : end_idx + 1][column].to_numpy(dtype=float)
            if not (np.isfinite(ref_values).all() and np.isfinite(cand_values).all()):
                invalid = True
                break
            try:
                distance, correlation = feature_comparison(ref_values, cand_values, column)
            except ValueError:
                invalid = True
                break
            distances.append(distance)
            correlations[column] = correlation
        if invalid:
            continue

        combined_distance = float(np.sqrt(np.mean(np.square(distances))))
        similarity = float(100.0 * np.exp(-combined_distance))
        record = {
            "_start_idx": start_idx,
            "_end_idx": end_idx,
            "开始日期": frame.at[start_idx, DATE_COLUMN],
            "结束日期": frame.at[end_idx, DATE_COLUMN],
            "相似度得分": similarity,
            "平均相关系数": float(np.mean(list(correlations.values()))),
        }
        if "收盘价(元)" in frame.columns:
            close_start = float(frame.at[start_idx, "收盘价(元)"])
            close_end = float(frame.at[end_idx, "收盘价(元)"])
            future_close = float(frame.at[end_idx + horizon, "收盘价(元)"])
            record["区间收盘涨跌幅"] = close_end / close_start - 1.0 if close_start else np.nan
            record[f"随后{horizon}期收盘涨跌幅"] = future_close / close_end - 1.0 if close_end else np.nan
        for column, value in correlations.items():
            record[f"相关_{column}"] = value
        candidates.append(record)

    candidates.sort(key=lambda item: (item["相似度得分"], item["平均相关系数"]), reverse=True)
    selected: list[dict] = []
    for candidate in candidates:
        if any(
            windows_overlap(candidate["_start_idx"], candidate["_end_idx"], other["_start_idx"], other["_end_idx"])
            for other in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= top_n:
            break

    if not selected:
        raise ValueError(
            "No complete candidate window was found. Widen the search range, shorten the reference window, or reduce the forecast horizon."
        )
    visible = [{key: value for key, value in row.items() if not key.startswith("_")} for row in selected]
    result = pd.DataFrame(visible)
    result.insert(0, "排名", range(1, len(result) + 1))
    return result, selected


def plot_reference_raw(frame: "pd.DataFrame", start_idx: int, end_idx: int, output: Path) -> None:
    columns = [column for column in FEATURE_COLUMNS if column in frame.columns]
    period = frame.iloc[start_idx : end_idx + 1]
    fig, axes = plt.subplots(len(columns), 1, figsize=(13, max(8, 2.3 * len(columns))), sharex=True)
    axes = np.atleast_1d(axes)
    for axis, column in zip(axes, columns):
        values = period[column].to_numpy(dtype=float)
        label = ENGLISH_NAMES[column]
        if column == "涨跌幅" and np.nanmax(np.abs(values)) <= 2:
            values = values * 100.0
            label += " [%]"
        axis.plot(period[DATE_COLUMN], values, color="#B8860B", linewidth=1.5)
        axis.set_ylabel(label)
        axis.grid(alpha=0.22)
    axes[-1].xaxis.set_major_locator(mdates.AutoDateLocator())
    axes[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(axes[-1].xaxis.get_major_locator()))
    fig.suptitle(f"Selected period: {period[DATE_COLUMN].iloc[0]:%Y-%m-%d} to {period[DATE_COLUMN].iloc[-1]:%Y-%m-%d}")
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    fig.savefig(output, dpi=170, bbox_inches="tight")
    plt.close(fig)


def plot_match_overlays(
    frame: "pd.DataFrame",
    features: list[str],
    ref_start_idx: int,
    ref_end_idx: int,
    matches: list[dict],
    output: Path,
) -> None:
    reference = frame.iloc[ref_start_idx : ref_end_idx + 1]
    x = np.arange(len(reference))
    fig, axes = plt.subplots(len(features), 1, figsize=(13, max(6, 3.0 * len(features))), sharex=True)
    axes = np.atleast_1d(axes)
    colors = plt.cm.tab10(np.linspace(0, 1, max(1, len(matches))))
    for axis, column in zip(axes, features):
        ref = z_normalize(transformed(reference[column].to_numpy(dtype=float), column))
        axis.plot(x, ref, color="black", linewidth=2.6, label=f"Reference {reference[DATE_COLUMN].iloc[0]:%Y-%m-%d}")
        for rank, (match, color) in enumerate(zip(matches, colors), 1):
            window = frame.iloc[match["_start_idx"] : match["_end_idx"] + 1]
            values = z_normalize(transformed(window[column].to_numpy(dtype=float), column))
            axis.plot(x, values, color=color, linewidth=1.35, alpha=0.88, label=f"#{rank} {window[DATE_COLUMN].iloc[0]:%Y-%m-%d}")
        axis.set_ylabel(f"{ENGLISH_NAMES[column]}\nnormalized")
        axis.grid(alpha=0.22)
    axes[0].legend(ncol=2, fontsize=8, loc="best")
    axes[-1].set_xlabel("Observation number within window")
    fig.suptitle("Reference window vs historical analogs (scale-free shape)")
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(output, dpi=170, bbox_inches="tight")
    plt.close(fig)


def build_future_paths(
    frame: "pd.DataFrame", matches: list[dict], horizon: int, ref_end_idx: int
) -> "pd.DataFrame":
    if "收盘价(元)" not in frame.columns:
        return pd.DataFrame()
    rows: list[dict] = []
    for rank, match in enumerate(matches, 1):
        end_idx = match["_end_idx"]
        base = float(frame.at[end_idx, "收盘价(元)"])
        for step in range(horizon + 1):
            idx = end_idx + step
            rows.append(
                {
                    "系列": f"历史匹配#{rank}",
                    "排名": rank,
                    "步数": step,
                    "日期": frame.at[idx, DATE_COLUMN],
                    "收盘价": frame.at[idx, "收盘价(元)"],
                    "相对匹配结束涨跌幅": frame.at[idx, "收盘价(元)"] / base - 1.0 if base else np.nan,
                }
            )
    if ref_end_idx + horizon < len(frame):
        base = float(frame.at[ref_end_idx, "收盘价(元)"])
        for step in range(horizon + 1):
            idx = ref_end_idx + step
            rows.append(
                {
                    "系列": "目标区间实际后续",
                    "排名": 0,
                    "步数": step,
                    "日期": frame.at[idx, DATE_COLUMN],
                    "收盘价": frame.at[idx, "收盘价(元)"],
                    "相对匹配结束涨跌幅": frame.at[idx, "收盘价(元)"] / base - 1.0 if base else np.nan,
                }
            )
    return pd.DataFrame(rows)


def plot_future_scenarios(paths: "pd.DataFrame", output: Path) -> None:
    if paths.empty:
        return
    historical = paths[paths["排名"] > 0]
    pivot = historical.pivot(index="步数", columns="排名", values="相对匹配结束涨跌幅") * 100.0
    fig, axis = plt.subplots(figsize=(12, 6.5))
    for column in pivot.columns:
        axis.plot(pivot.index, pivot[column], alpha=0.48, linewidth=1.2, label=f"Analog #{column}")
    median = pivot.median(axis=1)
    low = pivot.quantile(0.20, axis=1)
    high = pivot.quantile(0.80, axis=1)
    axis.plot(median.index, median, color="#B22222", linewidth=2.6, label="Analog median")
    axis.fill_between(median.index, low, high, color="#B22222", alpha=0.14, label="20th–80th percentile")
    actual = paths[paths["排名"] == 0]
    if not actual.empty:
        axis.plot(
            actual["步数"],
            actual["相对匹配结束涨跌幅"] * 100.0,
            color="black",
            linestyle="--",
            linewidth=2.0,
            label="Actual path after reference",
        )
    axis.axhline(0, color="grey", linewidth=0.8)
    axis.set_xlabel("Observations after window end")
    axis.set_ylabel("Close-price change from window end [%]")
    axis.set_title("What happened after the historical analogs (scenario range, not a forecast)")
    axis.grid(alpha=0.22)
    axis.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(output, dpi=170, bbox_inches="tight")
    plt.close(fig)


def build_matched_windows(
    frame: "pd.DataFrame", features: list[str], matches: list[dict]
) -> "pd.DataFrame":
    rows: list[dict] = []
    for rank, match in enumerate(matches, 1):
        window = frame.iloc[match["_start_idx"] : match["_end_idx"] + 1]
        normalized = {
            column: z_normalize(transformed(window[column].to_numpy(dtype=float), column)) for column in features
        }
        for offset, (_, source_row) in enumerate(window.iterrows()):
            row = {"排名": rank, "区间内序号": offset, DATE_COLUMN: source_row[DATE_COLUMN]}
            for column in features:
                row[column] = source_row[column]
                row[f"标准化_{column}"] = normalized[column][offset]
            rows.append(row)
    return pd.DataFrame(rows)


def flat_regime_warning(frame: "pd.DataFrame") -> None:
    if "收盘价(元)" not in frame.columns or len(frame) < 2:
        return
    close = frame["收盘价(元)"].to_numpy(dtype=float)
    valid = np.isfinite(close[:-1]) & np.isfinite(close[1:])
    if not valid.any():
        return
    unchanged = float(np.mean(np.isclose(close[1:][valid], close[:-1][valid], rtol=0, atol=1e-12)))
    if unchanged >= 0.10:
        say(
            f"Warning: {unchanged:.1%} of consecutive close-price observations are unchanged; fixed-price regimes can dominate similarity results.",
            f"警告：{unchanged:.1%} 的相邻收盘价完全不变；固定价格时期可能主导相似度结果。",
        )


def write_summary(
    path: Path,
    source: Path,
    sheet: str,
    frame: "pd.DataFrame",
    features: list[str],
    ref_start_idx: int,
    ref_end_idx: int,
    search_start: "pd.Timestamp",
    search_end: "pd.Timestamp",
    horizon: int,
    matches_table: "pd.DataFrame",
) -> None:
    lines = [
        "Gold Historical Pattern Finder / 黄金历史形态匹配",
        f"Source: {source}",
        f"Sheet: {sheet}",
        f"Usable observations: {len(frame)}",
        f"Reference: {frame.at[ref_start_idx, DATE_COLUMN]:%Y-%m-%d} to {frame.at[ref_end_idx, DATE_COLUMN]:%Y-%m-%d}",
        f"Reference length: {ref_end_idx - ref_start_idx + 1} observations",
        f"Search range: {search_start:%Y-%m-%d} to {search_end:%Y-%m-%d}",
        f"Features: {', '.join(features)}",
        f"Forward scenario horizon: {horizon} observations",
        "",
        "Method: price columns use cumulative log-price trajectories; turnover and volume use log(1+x); change uses its supplied values. Each feature is z-normalized within every window. Windows are ranked by normalized RMS distance and reported as a 0–100 similarity score (100 means identical normalized shape).",
        "方法：价格列使用累计对数价格轨迹；成交额和成交量使用 log(1+x)；涨跌幅使用原始数值。每个窗口内的各项变量均进行 z 标准化。窗口按标准化均方根距离排序，并转换成 0–100 的相似度得分（100 表示标准化形状完全相同）。",
        "",
        "Important: analog paths are descriptive scenarios, not probabilities or trading advice. Similar patterns can have different outcomes, and market regimes, inflation, exchange rates, liquidity, and policy structures change over time.",
        "重要：历史类比路径只是描述性情景，不是概率预测或投资建议。相似形态可能产生不同结果，而且市场制度、通胀、汇率、流动性和政策结构会随时间改变。",
        "",
        matches_table.to_string(index=False),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    configure_chinese_font()
    say(
        "Gold Historical Pattern Finder — exploratory analog analysis",
        "黄金历史形态匹配工具——探索性类比分析",
    )
    default_file = Path.home() / "Desktop" / "SPTAUUSDOZ.IDC.xlsx"
    raw_path = input(f"Input Excel/CSV path / 输入文件路径 [{default_file}]: ").strip()
    source = clean_path(raw_path) if raw_path else default_file.resolve()
    if not source.exists():
        raise FileNotFoundError(f"File not found: {source}\nYou can drag the file from Desktop into the terminal at this prompt.")

    raw_frame, sheet = read_input_file(source)
    frame, stats = prepare_data(raw_frame)
    say(
        f"Imported {stats['original_rows']:,} rows from '{sheet}'; retained {len(frame):,} unique dated rows.",
        f"已从“{sheet}”导入 {stats['original_rows']:,} 行；保留 {len(frame):,} 行具有唯一日期的数据。",
    )
    if stats["invalid_dates"] or stats["duplicate_dates"]:
        say(
            f"Removed {stats['invalid_dates']} invalid-date rows and {stats['duplicate_dates']} duplicate dates (kept the last occurrence).",
            f"删除了 {stats['invalid_dates']} 行无效日期，并处理了 {stats['duplicate_dates']} 个重复日期（保留最后一条）。",
        )
    flat_regime_warning(frame)

    features = choose_features(frame)
    required = list(dict.fromkeys([DATE_COLUMN, *features, "收盘价(元)"]))
    required = [column for column in required if column in frame.columns]
    before_missing = len(frame)
    frame = frame.dropna(subset=[column for column in required if column != DATE_COLUMN]).reset_index(drop=True)
    if len(frame) != before_missing:
        say(
            f"Dropped {before_missing - len(frame):,} rows missing a selected variable.",
            f"删除了 {before_missing - len(frame):,} 行缺少所选变量的数据。",
        )

    ref_start_idx, ref_end_idx = choose_reference_window(frame)
    length = ref_end_idx - ref_start_idx + 1
    say(
        f"Reference window: {frame.at[ref_start_idx, DATE_COLUMN]:%Y-%m-%d} to {frame.at[ref_end_idx, DATE_COLUMN]:%Y-%m-%d}, {length} observations.",
        f"目标区间：{frame.at[ref_start_idx, DATE_COLUMN]:%Y-%m-%d} 至 {frame.at[ref_end_idx, DATE_COLUMN]:%Y-%m-%d}，共 {length} 个观测值。",
    )
    match_features, constant_features = informative_reference_features(frame, features, ref_start_idx, ref_end_idx)
    if constant_features:
        say(
            f"Excluded constant reference variables from matching: {', '.join(constant_features)}.",
            f"已从相似度匹配中排除目标区间内不变的变量：{', '.join(constant_features)}。",
        )
    if not match_features:
        raise ValueError("Every selected variable is constant in the reference window; there is no trend shape to match.")
    search_start, search_end = choose_search_range(frame, ref_start_idx)
    horizon_default = min(20, max(5, length // 3))
    horizon = prompt_int("Forward scenario horizon in observations / 后续情景长度（观测期数）", horizon_default, 1)
    top_n = prompt_int("Number of distinct historical matches / 不重叠历史匹配数量", 5, 1, 20)

    output_default = source.parent / f"GoldTrendResults_{datetime.now():%Y%m%d_%H%M%S}"
    raw_output = input(f"Output folder / 输出文件夹 [{output_default}]: ").strip()
    output_dir = clean_path(raw_output) if raw_output else output_default
    output_dir.mkdir(parents=True, exist_ok=True)

    matches_table, matches = find_matches(
        frame,
        match_features,
        ref_start_idx,
        ref_end_idx,
        search_start,
        search_end,
        horizon,
        top_n,
    )

    reference = frame.iloc[ref_start_idx : ref_end_idx + 1]
    matched_windows = build_matched_windows(frame, match_features, matches)
    future_paths = build_future_paths(frame, matches, horizon, ref_end_idx)
    reference.to_csv(output_dir / "selected_period.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    matches_table.to_csv(output_dir / "matches.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    matched_windows.to_csv(output_dir / "matched_windows_long.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    if not future_paths.empty:
        future_paths.to_csv(output_dir / "analog_future_close.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")

    plot_reference_raw(frame, ref_start_idx, ref_end_idx, output_dir / "selected_period_all_variables.png")
    plot_match_overlays(frame, match_features, ref_start_idx, ref_end_idx, matches, output_dir / "historical_match_overlays.png")
    plot_future_scenarios(future_paths, output_dir / "analog_forward_scenarios.png")
    write_summary(
        output_dir / "analysis_summary.txt",
        source,
        sheet,
        frame,
        match_features,
        ref_start_idx,
        ref_end_idx,
        search_start,
        search_end,
        horizon,
        matches_table,
    )

    display_columns = ["排名", "开始日期", "结束日期", "相似度得分", "平均相关系数"]
    optional = [column for column in matches_table.columns if column.startswith("随后")]
    display_columns.extend(optional[:1])
    display = matches_table[display_columns].copy()
    display["开始日期"] = display["开始日期"].dt.strftime("%Y-%m-%d")
    display["结束日期"] = display["结束日期"].dt.strftime("%Y-%m-%d")
    say("Top distinct matches:", "最相似的不重叠历史区间：")
    print(display.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    say(f"Results saved to: {output_dir}", f"结果已保存至：{output_dir}")
    say(
        "Treat the forward paths as historical scenarios, not a prediction or trading signal.",
        "请把后续路径视为历史情景，而不是预测或交易信号。",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled / 已取消")
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nError / 错误: {exc}", file=sys.stderr)
        raise SystemExit(1)
