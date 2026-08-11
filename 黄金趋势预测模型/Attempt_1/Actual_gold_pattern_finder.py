#!/usr/bin/env python3
"""黄金历史相似走势分析工具。

读取 Excel/CSV 时间序列后，按照用户选择的目标区间和历史搜索范围，
寻找形状最相似且互不重叠的历史区间，并输出图表与结果表格。
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
        missing = getattr(exc, "name", "所需依赖包")
        print(f"缺少 Python 依赖包：{missing}")
        print("请运行以下命令安装：")
        print("  python3 -m pip install pandas numpy matplotlib openpyxl")
        raise SystemExit(1) from exc
    return np, pd, plt, mdates, font_manager


np, pd, plt, mdates, font_manager = _load_dependencies()


DATE_COLUMN = "日期"
PRICE_COLUMNS = ["开盘价(元)", "最高价(元)", "最低价(元)", "收盘价(元)"]
OTHER_COLUMNS = ["涨跌幅", "成交额(百万)", "成交量(股)"]
FEATURE_COLUMNS = PRICE_COLUMNS + OTHER_COLUMNS


def clean_path(text: str) -> Path:
    """兼容普通文件路径以及直接拖入终端后产生的路径。"""
    text = text.strip().strip("\"'")
    text = text.replace("\\ ", " ")
    return Path(os.path.expandvars(os.path.expanduser(text))).resolve()


def configure_chinese_font() -> None:
    common_font_files = [
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/STHeiti Light.ttc"),
        Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for font_path in common_font_files:
        if font_path.exists():
            font_manager.fontManager.addfont(str(font_path))
            font_name = font_manager.FontProperties(fname=str(font_path)).get_name()
            plt.rcParams["font.sans-serif"] = [font_name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return

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
            print("请输入整数。")
            continue
        if value < minimum or (maximum is not None and value > maximum):
            print(f"数值必须至少为 {minimum}{'，且不超过 '+str(maximum) if maximum is not None else ''}。")
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
            print("可用工作表：")
            for i, name in enumerate(sheets, 1):
                print(f"  {i}. {name}")
            choice = prompt_int("请输入工作表编号", 1, 1, len(sheets))
            sheet = sheets[choice - 1]
        frame = pd.read_excel(book, sheet_name=sheet)
        return frame, sheet
    if suffix == ".csv":
        for encoding in ("utf-8-sig", "gb18030", "utf-8"):
            try:
                return pd.read_csv(path, encoding=encoding), "CSV文件"
            except UnicodeDecodeError:
                continue
        raise ValueError("无法识别 CSV 文件的编码格式。")
    raise ValueError("仅支持 .xlsx、.xlsm 和 .csv 文件。")


def prepare_data(frame: "pd.DataFrame") -> tuple["pd.DataFrame", dict[str, int]]:
    frame = frame.copy()
    frame.columns = [re.sub(r"\s+", "", str(c)) for c in frame.columns]
    if DATE_COLUMN not in frame.columns:
        raise ValueError(f"没有找到必需的“{DATE_COLUMN}”列。当前列名：{list(frame.columns)}")

    available = [column for column in FEATURE_COLUMNS if column in frame.columns]
    if not available:
        raise ValueError("没有找到预期的价格、涨跌幅、成交额或成交量列。")

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
    print("请选择用于寻找相似走势的变量：")
    print("  0. 全部可用变量")
    for i, column in enumerate(available, 1):
        print(f"  {i}. {column}")
    while True:
        raw = input("请输入编号，例如 4 或 1,2,3 [0]: ").strip() or "0"
        if raw == "0":
            return available
        try:
            indices = sorted({int(item.strip()) for item in raw.split(",")})
        except ValueError:
            print("请输入数字；选择多个变量时请用逗号分隔。")
            continue
        if indices and all(1 <= item <= len(available) for item in indices):
            return [available[item - 1] for item in indices]
        print("一个或多个编号超出可选范围。")


def prompt_date(prompt: str, default: "pd.Timestamp | None" = None) -> "pd.Timestamp | None":
    default_text = default.strftime("%Y-%m-%d") if default is not None else "留空"
    while True:
        raw = input(f"{prompt} [{default_text}]: ").strip()
        if not raw:
            return default
        try:
            return pd.Timestamp(raw).normalize()
        except Exception:
            print("请输入可识别的日期，例如 2024-01-31。")


def snap_start(dates: "pd.Series", requested: "pd.Timestamp") -> "pd.Timestamp":
    candidates = dates[dates >= requested]
    if candidates.empty:
        raise ValueError("输入的开始日期晚于数据中的最后日期。")
    return pd.Timestamp(candidates.iloc[0])


def snap_end(dates: "pd.Series", requested: "pd.Timestamp") -> "pd.Timestamp":
    candidates = dates[dates <= requested]
    if candidates.empty:
        raise ValueError("输入的结束日期早于数据中的最早日期。")
    return pd.Timestamp(candidates.iloc[-1])


def choose_reference_window(frame: "pd.DataFrame") -> tuple[int, int]:
    dates = frame[DATE_COLUMN]
    print(f"可用日期范围：{dates.iloc[0]:%Y-%m-%d} 至 {dates.iloc[-1]:%Y-%m-%d}，共 {len(frame):,} 个数据点。")
    raw_start = input("请输入目标区间的开始日期（留空则分析最近一段数据）: ").strip()
    if not raw_start:
        recent = prompt_int("要分析最近多少个数据点", 60, 3, len(frame))
        return len(frame) - recent, len(frame) - 1

    try:
        requested_start = pd.Timestamp(raw_start).normalize()
    except Exception as exc:
        raise ValueError("无法识别目标区间的开始日期。") from exc
    actual_start = snap_start(dates, requested_start)
    requested_end = prompt_date("请输入目标区间的结束日期", dates.iloc[-1])
    actual_end = snap_end(dates, requested_end)
    if actual_end < actual_start:
        raise ValueError("目标区间的结束日期不能早于开始日期。")
    start_idx = int(dates.searchsorted(actual_start, side="left"))
    end_idx = int(dates.searchsorted(actual_end, side="right") - 1)
    if end_idx - start_idx + 1 < 3:
        raise ValueError("目标区间至少需要包含 3 个数据点。")
    if actual_start != requested_start or actual_end != requested_end:
        print(f"输入日期没有对应数据，已自动调整为：{actual_start:%Y-%m-%d} 至 {actual_end:%Y-%m-%d}。")
    return start_idx, end_idx


def choose_search_range(frame: "pd.DataFrame", ref_start_idx: int) -> tuple["pd.Timestamp", "pd.Timestamp"]:
    dates = frame[DATE_COLUMN]
    default_end_idx = max(0, ref_start_idx - 1)
    requested_start = prompt_date("从哪一天开始搜索历史相似走势（留空则从最早数据开始）", dates.iloc[0])
    requested_end = prompt_date(
        "搜索到哪一天为止（默认到目标区间开始之前）",
        dates.iloc[default_end_idx],
    )
    actual_start = snap_start(dates, requested_start)
    actual_end = snap_end(dates, requested_end)
    if actual_end < actual_start:
        raise ValueError("历史搜索的结束日期不能早于开始日期。")
    return actual_start, actual_end


def transformed(values: "np.ndarray", column: str) -> "np.ndarray":
    values = np.asarray(values, dtype=float)
    if column in PRICE_COLUMNS:
        if np.any(values <= 0):
            raise ValueError(f"“{column}”中存在零或负数，无法进行对数价格匹配。")
        return np.log(values / values[0])
    if column in {"成交额(百万)", "成交量(股)"}:
        if np.any(values < 0):
            raise ValueError(f"“{column}”中存在负数。")
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
    """排除目标区间内没有变化、因而无法用于比较形状的变量。"""
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
        raise ValueError("没有找到完整的历史匹配区间。请扩大搜索范围、缩短目标区间，或减少后续查看的数据点数量。")
    visible = [{key: value for key, value in row.items() if not key.startswith("_")} for row in selected]
    result = pd.DataFrame(visible)
    result.insert(0, "排名", range(1, len(result) + 1))
    return result, selected


def plot_reference_raw(frame: "pd.DataFrame", start_idx: int, end_idx: int, output: Path) -> None:
    period = frame.iloc[start_idx : end_idx + 1]
    columns = [
        column
        for column in FEATURE_COLUMNS
        if column in frame.columns
        and np.isfinite(period[column].to_numpy(dtype=float)).any()
        and float(np.nanstd(period[column].to_numpy(dtype=float))) >= 1e-12
    ]
    if not columns:
        raise ValueError("目标区间内的所有可绘制变量都没有变化。")
    fig, axes = plt.subplots(len(columns), 1, figsize=(10, max(8, 2.3 * len(columns))), sharex=True)
    axes = np.atleast_1d(axes)
    for axis, column in zip(axes, columns):
        values = period[column].to_numpy(dtype=float)
        label = column
        if column == "涨跌幅" and np.nanmax(np.abs(values)) <= 2:
            values = values * 100.0
            label = "涨跌幅（%）"
        axis.plot(period[DATE_COLUMN], values, color="#B8860B", linewidth=1.5)
        axis.set_ylabel(label)
        axis.grid(alpha=0.22)
    axes[-1].xaxis.set_major_locator(mdates.AutoDateLocator())
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    axes[-1].set_xlabel("日期")
    fig.suptitle(f"目标区间：{period[DATE_COLUMN].iloc[0]:%Y-%m-%d} 至 {period[DATE_COLUMN].iloc[-1]:%Y-%m-%d}")
    fig.autofmt_xdate(rotation=30, ha="right")
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
        reference_label = f"目标区间：{reference[DATE_COLUMN].iloc[0]:%Y-%m-%d} 至 {reference[DATE_COLUMN].iloc[-1]:%Y-%m-%d}"
        axis.plot(x, ref, color="black", linewidth=2.6, label=reference_label)
        for match, color in zip(matches, colors):
            window = frame.iloc[match["_start_idx"] : match["_end_idx"] + 1]
            values = z_normalize(transformed(window[column].to_numpy(dtype=float), column))
            date_label = f"{window[DATE_COLUMN].iloc[0]:%Y-%m-%d} 至 {window[DATE_COLUMN].iloc[-1]:%Y-%m-%d}"
            axis.plot(x, values, color=color, linewidth=1.35, alpha=0.88, label=date_label)
        axis.set_ylabel(f"{column}\n（标准化走势）")
        axis.grid(alpha=0.22)
    axes[0].legend(ncol=2, fontsize=8, loc="best")
    axes[-1].set_xlabel("区间内数据点序号")
    fig.suptitle("目标区间与历史相似走势对比")
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
        start_idx = match["_start_idx"]
        end_idx = match["_end_idx"]
        period_label = f"{frame.at[start_idx, DATE_COLUMN]:%Y-%m-%d} 至 {frame.at[end_idx, DATE_COLUMN]:%Y-%m-%d}"
        base = float(frame.at[end_idx, "收盘价(元)"])
        for step in range(horizon + 1):
            idx = end_idx + step
            rows.append(
                {
                    "匹配区间": period_label,
                    "排名": rank,
                    "后续数据点序号": step,
                    "日期": frame.at[idx, DATE_COLUMN],
                    "收盘价(元)": frame.at[idx, "收盘价(元)"],
                    "相对区间结束时的涨跌幅": frame.at[idx, "收盘价(元)"] / base - 1.0 if base else np.nan,
                }
            )
    if ref_end_idx + horizon < len(frame):
        base = float(frame.at[ref_end_idx, "收盘价(元)"])
        for step in range(horizon + 1):
            idx = ref_end_idx + step
            rows.append(
                {
                    "匹配区间": "目标区间实际后续走势",
                    "排名": 0,
                    "后续数据点序号": step,
                    "日期": frame.at[idx, DATE_COLUMN],
                    "收盘价(元)": frame.at[idx, "收盘价(元)"],
                    "相对区间结束时的涨跌幅": frame.at[idx, "收盘价(元)"] / base - 1.0 if base else np.nan,
                }
            )
    return pd.DataFrame(rows)


def plot_future_paths(paths: "pd.DataFrame", output: Path) -> None:
    if paths.empty:
        return
    historical = paths[paths["排名"] > 0]
    pivot = historical.pivot(
        index="后续数据点序号", columns="匹配区间", values="相对区间结束时的涨跌幅"
    ) * 100.0
    fig, axis = plt.subplots(figsize=(12, 6.5))
    for column in pivot.columns:
        axis.plot(pivot.index, pivot[column], alpha=0.55, linewidth=1.3, label=column)
    median = pivot.median(axis=1)
    low = pivot.quantile(0.20, axis=1)
    high = pivot.quantile(0.80, axis=1)
    axis.plot(median.index, median, color="#B22222", linewidth=2.6, label="历史匹配中位数")
    axis.fill_between(median.index, low, high, color="#B22222", alpha=0.14, label="第20–80百分位区间")
    actual = paths[paths["排名"] == 0]
    if not actual.empty:
        axis.plot(
            actual["后续数据点序号"],
            actual["相对区间结束时的涨跌幅"] * 100.0,
            color="black",
            linestyle="--",
            linewidth=2.0,
            label="目标区间实际后续走势",
        )
    axis.axhline(0, color="grey", linewidth=0.8)
    axis.set_xlabel("区间结束后的数据点序号")
    axis.set_ylabel("相对区间结束时的收盘价涨跌幅（%）")
    axis.set_title("历史匹配区间后续走势")
    axis.grid(alpha=0.22)
    axis.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(output, dpi=170, bbox_inches="tight")
    plt.close(fig)


def flat_regime_warning(frame: "pd.DataFrame") -> None:
    if "收盘价(元)" not in frame.columns or len(frame) < 2:
        return
    close = frame["收盘价(元)"].to_numpy(dtype=float)
    valid = np.isfinite(close[:-1]) & np.isfinite(close[1:])
    if not valid.any():
        return
    unchanged = float(np.mean(np.isclose(close[1:][valid], close[:-1][valid], rtol=0, atol=1e-12)))
    if unchanged >= 0.10:
        print(f"提示：{unchanged:.1%} 的相邻收盘价完全不变，固定价格时期可能影响相似度结果。")


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
        "黄金历史相似走势分析",
        f"数据文件：{source}",
        f"工作表：{sheet}",
        f"可用数据点：{len(frame)}",
        f"目标区间：{frame.at[ref_start_idx, DATE_COLUMN]:%Y-%m-%d} 至 {frame.at[ref_end_idx, DATE_COLUMN]:%Y-%m-%d}",
        f"目标区间长度：{ref_end_idx - ref_start_idx + 1} 个数据点",
        f"历史搜索范围：{search_start:%Y-%m-%d} 至 {search_end:%Y-%m-%d}",
        f"参与匹配的变量：{', '.join(features)}",
        f"每个匹配区间结束后查看：{horizon} 个数据点",
        "",
        "方法：价格列使用累计对数价格轨迹；成交额和成交量使用 log(1+x)；涨跌幅使用原始数值。每个窗口内的各项变量均进行 z 标准化。窗口按标准化均方根距离排序，并转换成 0–100 的相似度得分（100 表示标准化形状完全相同）。",
        "",
        matches_table.to_string(index=False),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    configure_chinese_font()
    print("黄金历史相似走势分析")
    default_file = ".../.xlsx" 
    raw_path = input(f"请输入 Excel/CSV 文件路径 [{default_file}]: ").strip()
    source = clean_path(raw_path) if raw_path else default_file.resolve()
    if not source.exists():
        raise FileNotFoundError(f"找不到文件：{source}\n也可以把桌面上的文件直接拖到终端窗口中。")

    raw_frame, sheet = read_input_file(source)
    frame, stats = prepare_data(raw_frame)
    print(f"已从“{sheet}”导入 {stats['original_rows']:,} 行，整理后保留 {len(frame):,} 行有效日期数据。")
    if stats["invalid_dates"] or stats["duplicate_dates"]:
        print(f"其中删除了 {stats['invalid_dates']} 行无效日期，并处理了 {stats['duplicate_dates']} 个重复日期（保留最后一条）。")
    flat_regime_warning(frame)

    features = choose_features(frame)
    required = list(dict.fromkeys([DATE_COLUMN, *features, "收盘价(元)"]))
    required = [column for column in required if column in frame.columns]
    before_missing = len(frame)
    frame = frame.dropna(subset=[column for column in required if column != DATE_COLUMN]).reset_index(drop=True)
    if len(frame) != before_missing:
        print(f"已删除 {before_missing - len(frame):,} 行缺少所选变量的数据。")

    ref_start_idx, ref_end_idx = choose_reference_window(frame)
    length = ref_end_idx - ref_start_idx + 1
    print(f"目标区间：{frame.at[ref_start_idx, DATE_COLUMN]:%Y-%m-%d} 至 {frame.at[ref_end_idx, DATE_COLUMN]:%Y-%m-%d}，共 {length} 个数据点。")
    match_features, constant_features = informative_reference_features(frame, features, ref_start_idx, ref_end_idx)
    if constant_features:
        print(f"以下变量在目标区间内没有变化，已自动排除：{', '.join(constant_features)}。")
    if not match_features:
        raise ValueError("所选变量在目标区间内全部没有变化，无法比较走势形状。")
    search_start, search_end = choose_search_range(frame, ref_start_idx)
    horizon_default = min(20, max(5, length // 3))
    horizon = prompt_int("每个历史匹配区间结束后，再查看多少个数据点", horizon_default, 1)
    top_n = prompt_int("希望找出多少个互不重叠的历史相似区间", 5, 1, 20)

    output_default = source.parent / f"黄金走势分析结果_{datetime.now():%Y%m%d_%H%M%S}"
    raw_output = input(f"结果保存位置 [{output_default}]: ").strip()
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
    future_paths = build_future_paths(frame, matches, horizon, ref_end_idx)
    reference.to_csv(output_dir / "目标区间数据.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    matches_table.to_csv(output_dir / "历史匹配结果.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    if not future_paths.empty:
        future_paths.to_csv(output_dir / "历史匹配后续走势.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")

    plot_reference_raw(frame, ref_start_idx, ref_end_idx, output_dir / "目标区间各变量.png")
    plot_match_overlays(frame, match_features, ref_start_idx, ref_end_idx, matches, output_dir / "历史相似走势对比.png")
    plot_future_paths(future_paths, output_dir / "历史匹配后续走势.png")
    write_summary(
        output_dir / "分析摘要.txt",
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
    print("\n最相似且互不重叠的历史区间：")
    print(display.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print(f"\n结果已保存至：{output_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已取消。")
        raise SystemExit(130)
    except Exception as exc:
        print(f"\n运行出错：{exc}", file=sys.stderr)
        raise SystemExit(1)
