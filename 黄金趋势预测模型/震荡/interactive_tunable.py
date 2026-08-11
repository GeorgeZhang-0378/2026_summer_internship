#!/usr/bin/env python3
"""市场状态识别、历史相似阶段检索与未来区间分析。

功能：
1. 从 Excel (.xlsx) 或 CSV 读取 OHLC 时间序列；
2. 用滚动窗口提取趋势、震荡、波动率和区间位置特征；
3. 用 Gaussian Mixture Model (GMM) 识别上涨、下跌、低波动震荡和高波动震荡；
4. 在同类历史状态中检索与当前窗口最相似且互不重叠的历史区间；
5. 根据历史相似样本生成未来收益的中位数及 50%/80% 预测区间；
6. 输出 CSV、JSON、TXT 和 PNG 图表。

本工具给出的“状态概率”是 GMM 的后验分类概率；
未来收益区间是历史相似样本的经验预测区间，不是保证收益。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

os.environ.setdefault("MPLCONFIGDIR", str(Path.home() / ".cache" / "market-regime-matplotlib"))

try:
    import numpy as np
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.mixture import GaussianMixture
    from sklearn.preprocessing import StandardScaler
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
except ImportError as exc:
    missing = getattr(exc, "name", "所需依赖")
    print(f"\n缺少 Python 依赖：{missing}", file=sys.stderr)
    print("请在当前 Python 环境中运行：", file=sys.stderr)
    print("  python -m pip install --upgrade pip setuptools wheel", file=sys.stderr)
    print("  python -m pip install numpy matplotlib scikit-learn", file=sys.stderr)
    print("注意：pip 安装名是 scikit-learn，但 Python 导入名是 sklearn。", file=sys.stderr)
    raise SystemExit(1) from exc


DATE_CANDIDATES = ["日期", "date", "Date", "DATE"]
OPEN_CANDIDATES = ["开盘价(元)", "开盘价", "open", "Open", "OPEN"]
HIGH_CANDIDATES = ["最高价(元)", "最高价", "high", "High", "HIGH"]
LOW_CANDIDATES = ["最低价(元)", "最低价", "low", "Low", "LOW"]
CLOSE_CANDIDATES = ["收盘价(元)", "收盘价", "close", "Close", "CLOSE"]

FEATURE_NAMES = [
    "有符号趋势强度",
    "趋势效率",
    "年化波动率",
    "窗口对数振幅",
    "均值穿越率",
    "涨跌反转率",
    "最近10期动量",
    "区间位置",
    "窗口总收益",
]
MODEL_FEATURE_INDEX = [0, 1, 2, 3, 4, 5, 6]

# 可调历史相似度权重：价格形状 + 市场特征 = 1
PATH_WEIGHT = 0.55
FEATURE_WEIGHT = 0.45

# 是否跳过同类GMM状态过滤，允许跨状态检索历史样本
# False=只检索同类状态（原行为）｜True=检索所有状态（样本量更大）
NO_REGIME_FILTER = False


@dataclass
class MarketData:
    dates: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    source_name: str


@dataclass
class WindowRecord:
    end_index: int
    features: np.ndarray
    regime_label: str = ""
    regime_probabilities: dict[str, float] | None = None


def configure_chinese_font() -> None:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for item in candidates:
        path = Path(item)
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            name = font_manager.FontProperties(fname=str(path)).get_name()
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return
    plt.rcParams["axes.unicode_minus"] = False


def column_number(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    if not letters:
        return 0
    result = 0
    for char in letters.group(0):
        result = result * 26 + (ord(char) - 64)
    return result - 1


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings: list[str] = []
    for si in root.findall("m:si", namespace):
        pieces = [node.text or "" for node in si.findall(".//m:t", namespace)]
        strings.append("".join(pieces))
    return strings


def _first_worksheet_path(zf: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    ns = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    first_sheet = workbook.find("m:sheets/m:sheet", ns)
    if first_sheet is None:
        raise ValueError("Excel 文件中没有工作表。")
    rel_id = first_sheet.attrib.get(f"{{{ns['r']}}}id")
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_ns = {"p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    for rel in rels.findall("p:Relationship", rel_ns):
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib["Target"].lstrip("/")
            if target.startswith("xl/"):
                return target
            return f"xl/{target}"
    raise ValueError("无法定位 Excel 第一张工作表。")


def read_xlsx_matrix(path: Path) -> list[list[object]]:
    """仅用 Python 标准库读取第一张工作表，避免依赖 pandas/openpyxl。"""
    with zipfile.ZipFile(path) as zf:
        shared = _xlsx_shared_strings(zf)
        worksheet_path = _first_worksheet_path(zf)
        root = ET.fromstring(zf.read(worksheet_path))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows_out: list[list[object]] = []
        max_col = 0
        for row in root.findall(".//m:sheetData/m:row", ns):
            sparse: dict[int, object] = {}
            for cell in row.findall("m:c", ns):
                ref = cell.attrib.get("r", "A1")
                col = column_number(ref)
                max_col = max(max_col, col)
                cell_type = cell.attrib.get("t")
                value_node = cell.find("m:v", ns)
                inline_node = cell.find("m:is/m:t", ns)
                if inline_node is not None:
                    value: object = inline_node.text or ""
                elif value_node is None:
                    value = None
                else:
                    raw = value_node.text or ""
                    if cell_type == "s":
                        value = shared[int(raw)] if raw else ""
                    elif cell_type in {"str", "inlineStr"}:
                        value = raw
                    elif cell_type == "b":
                        value = raw == "1"
                    else:
                        try:
                            value = float(raw)
                            if value.is_integer():
                                value = int(value)
                        except ValueError:
                            value = raw
                sparse[col] = value
            if sparse:
                current = [None] * (max_col + 1)
                for col, value in sparse.items():
                    if col >= len(current):
                        current.extend([None] * (col - len(current) + 1))
                    current[col] = value
                rows_out.append(current)
        width = max((len(row) for row in rows_out), default=0)
        return [row + [None] * (width - len(row)) for row in rows_out]


def read_csv_matrix(path: Path) -> list[list[object]]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return [row for row in csv.reader(handle)]
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"无法识别 CSV 编码：{last_error}")


def find_column(headers: list[str], candidates: Iterable[str], required: bool = True) -> int | None:
    normalized = {str(value).strip().replace(" ", "").lower(): i for i, value in enumerate(headers)}
    for candidate in candidates:
        key = candidate.strip().replace(" ", "").lower()
        if key in normalized:
            return normalized[key]
    if required:
        raise ValueError(f"缺少字段，候选名称为：{list(candidates)}；当前字段：{headers}")
    return None


def parse_float(value: object) -> float:
    if value is None or value == "":
        return math.nan
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "—", "--", "nan", "None"}:
        return math.nan
    return float(text)


def parse_date(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, (int, float)):
        return datetime(1899, 12, 30) + timedelta(days=float(value))
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def load_market_data(path: Path) -> MarketData:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        matrix = read_xlsx_matrix(path)
    elif suffix == ".csv":
        matrix = read_csv_matrix(path)
    else:
        raise ValueError("仅支持 .xlsx 和 .csv。")
    if len(matrix) < 3:
        raise ValueError("文件数据不足。")

    headers = [str(value).strip() if value is not None else "" for value in matrix[0]]
    date_col = find_column(headers, DATE_CANDIDATES)
    close_col = find_column(headers, CLOSE_CANDIDATES)
    open_col = find_column(headers, OPEN_CANDIDATES, required=False)
    high_col = find_column(headers, HIGH_CANDIDATES, required=False)
    low_col = find_column(headers, LOW_CANDIDATES, required=False)

    parsed: list[tuple[datetime, float, float, float, float]] = []
    for row in matrix[1:]:
        if date_col >= len(row) or close_col >= len(row):
            continue
        date = parse_date(row[date_col])
        close = parse_float(row[close_col])
        if date is None or not math.isfinite(close) or close <= 0:
            continue
        open_value = parse_float(row[open_col]) if open_col is not None and open_col < len(row) else close
        high_value = parse_float(row[high_col]) if high_col is not None and high_col < len(row) else close
        low_value = parse_float(row[low_col]) if low_col is not None and low_col < len(row) else close
        if not math.isfinite(open_value) or open_value <= 0:
            open_value = close
        if not math.isfinite(high_value) or high_value <= 0:
            high_value = max(open_value, close)
        if not math.isfinite(low_value) or low_value <= 0:
            low_value = min(open_value, close)
        high_value = max(high_value, open_value, close)
        low_value = min(low_value, open_value, close)
        parsed.append((date, open_value, high_value, low_value, close))

    parsed.sort(key=lambda item: item[0])
    deduplicated: dict[datetime, tuple[datetime, float, float, float, float]] = {}
    for item in parsed:
        deduplicated[item[0]] = item
    data = list(deduplicated.values())
    if len(data) < 200:
        raise ValueError("有效数据少于200条，无法建立稳定滚动模型。")

    return MarketData(
        dates=np.array([item[0] for item in data], dtype=object),
        open=np.array([item[1] for item in data], dtype=float),
        high=np.array([item[2] for item in data], dtype=float),
        low=np.array([item[3] for item in data], dtype=float),
        close=np.array([item[4] for item in data], dtype=float),
        source_name=path.name,
    )


def subset_from_date(data: MarketData, start_date: datetime) -> MarketData:
    mask = np.array([date >= start_date for date in data.dates], dtype=bool)
    if int(mask.sum()) < 300:
        raise ValueError(f"从 {start_date:%Y-%m-%d} 起的数据不足300条。")
    return MarketData(
        dates=data.dates[mask],
        open=data.open[mask],
        high=data.high[mask],
        low=data.low[mask],
        close=data.close[mask],
        source_name=data.source_name,
    )


def calculate_features(data: MarketData, end_index: int, window: int) -> np.ndarray:
    start = end_index - window + 1
    close = data.close[start : end_index + 1]
    high = data.high[start : end_index + 1]
    low = data.low[start : end_index + 1]
    log_close = np.log(close)
    returns = np.diff(log_close)
    x = np.arange(window, dtype=float)
    slope = float(np.polyfit(x, log_close, 1)[0])
    path_std = float(np.std(log_close)) + 1e-12
    signed_slope_strength = slope * (window - 1) / path_std
    total_return = float(log_close[-1] - log_close[0])
    efficiency = abs(total_return) / (float(np.sum(np.abs(returns))) + 1e-12)
    annualized_volatility = float(np.std(returns, ddof=1) * math.sqrt(252))
    log_range = float(math.log(np.max(high) / np.min(low)))

    centered = log_close - float(np.mean(log_close))
    centered_sign = np.sign(centered)
    centered_sign[centered_sign == 0] = 1
    mean_crossing_rate = float(np.mean(centered_sign[1:] != centered_sign[:-1]))

    return_sign = np.sign(returns)
    return_sign[return_sign == 0] = 1
    reversal_rate = float(np.mean(return_sign[1:] != return_sign[:-1])) if len(return_sign) > 1 else 0.0

    window_low = float(np.min(low))
    window_high = float(np.max(high))
    range_position = float((close[-1] - window_low) / (window_high - window_low + 1e-12))
    recent_points = min(10, window - 1)
    recent_momentum = float(log_close[-1] - log_close[-1 - recent_points])

    return np.array(
        [
            signed_slope_strength,
            efficiency,
            annualized_volatility,
            log_range,
            mean_crossing_rate,
            reversal_rate,
            recent_momentum,
            range_position,
            total_return,
        ],
        dtype=float,
    )


def build_feature_matrix(data: MarketData, window: int) -> tuple[np.ndarray, np.ndarray]:
    end_indices = np.arange(window - 1, len(data.close), dtype=int)
    features = np.vstack([calculate_features(data, int(end), window) for end in end_indices])
    finite = np.isfinite(features).all(axis=1)
    return end_indices[finite], features[finite]


def map_components_to_regimes(gmm: GaussianMixture, scaler: StandardScaler) -> dict[int, str]:
    means_raw = scaler.inverse_transform(gmm.means_)
    mapping: dict[int, str] = {}
    nontrend_components: list[int] = []
    for component, means in enumerate(means_raw):
        signed_slope = means[0]
        if signed_slope >= 1.40:
            mapping[component] = "上涨趋势"
        elif signed_slope <= -1.40:
            mapping[component] = "下跌趋势"
        else:
            nontrend_components.append(component)

    if nontrend_components:
        nontrend_vols = [means_raw[index, 2] for index in nontrend_components]
        volatility_cut = float(np.median(nontrend_vols))
        for index in nontrend_components:
            mapping[index] = "高波动震荡" if means_raw[index, 2] >= volatility_cut else "低波动震荡"
    return mapping


def aggregate_probabilities(component_probabilities: np.ndarray, mapping: dict[int, str]) -> dict[str, float]:
    result = {"上涨趋势": 0.0, "下跌趋势": 0.0, "低波动震荡": 0.0, "高波动震荡": 0.0}
    for component, probability in enumerate(component_probabilities):
        result[mapping[component]] += float(probability)
    return result


def stage_description(regime: str, features: np.ndarray) -> str:
    position = float(features[7])
    recent_momentum = float(features[6])
    if "震荡" in regime:
        if position <= 0.25:
            return "区间下沿反弹" if recent_momentum > 0 else "区间下沿测试"
        if position >= 0.75:
            return "区间上沿测试" if recent_momentum > 0 else "区间上沿回落"
        if recent_momentum > 0.015:
            return "区间中部向上运行"
        if recent_momentum < -0.015:
            return "区间中部向下运行"
        return "区间中部横向运行"
    if regime == "上涨趋势":
        if position >= 0.80:
            return "上涨趋势中，位于窗口高位"
        if recent_momentum < 0:
            return "上涨趋势中的短期回撤"
        return "上涨趋势延续阶段"
    if regime == "下跌趋势":
        if position <= 0.20:
            return "下跌趋势中，位于窗口低位"
        if recent_momentum > 0:
            return "下跌趋势中的短期反弹"
        return "下跌趋势延续阶段"
    return regime


def z_path(close: np.ndarray) -> np.ndarray:
    path = np.log(close / close[0])
    std = float(np.std(path))
    if std < 1e-12:
        return np.zeros_like(path)
    return (path - float(np.mean(path))) / std


def windows_overlap(a_end: int, b_end: int, window: int) -> bool:
    a_start = a_end - window + 1
    b_start = b_end - window + 1
    return max(a_start, b_start) <= min(a_end, b_end)


def weighted_quantile(values: np.ndarray, quantile: float, weights: np.ndarray) -> float:
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    if cumulative[-1] <= 0:
        return float(np.quantile(values, quantile))
    cumulative /= cumulative[-1]
    return float(np.interp(quantile, cumulative, sorted_values))


def logistic_direction_probability(
    matches: list[dict[str, object]],
    current_features: np.ndarray | None = None,
) -> float:
    """用逻辑回归替代加权计数估计 P(上涨|距离)。

    对每一条历史匹配，以 distance 和当前窗口的特征（如有）为输入，
    以 future_return > 0 为目标，用 L2 正则化逻辑回归建模，
    最后预测 distance=0（完全匹配当前窗口）时的上涨概率。

    相比加权计数，逻辑回归能自动学习"距离越近是否越可靠"，
    且在样本量较小时通过正则化避免过拟合。
    """
    n = len(matches)
    if n < 5:
        weights = np.array([float(m["weight"]) for m in matches], dtype=float)
        outcomes = np.array([1.0 if float(m["future_return"]) > 0 else 0.0 for m in matches], dtype=float)
        if weights.sum() <= 0:
            return 0.5
        return float(np.average(outcomes, weights=weights))

    # 特征矩阵：[distance, path_distance, feature_distance]
    X_list = []
    for m in matches:
        row = [float(m["distance"])]
        if "path_distance" in m:
            row.append(float(m["path_distance"]))
        if "feature_distance" in m:
            row.append(float(m["feature_distance"]))
        X_list.append(row)
    X = np.array(X_list, dtype=float)
    y = np.array([1.0 if float(m["future_return"]) > 0 else 0.0 for m in matches], dtype=float)

    if len(np.unique(y)) < 2:
        return float(y[0])

    # 正则化强度：样本越小越强
    C = max(0.02, n / 30.0)
    model = LogisticRegression(
        C=C, solver="lbfgs", random_state=42, max_iter=500
    )
    model.fit(X, y)

    # 预测 distance=0（即与当前窗口完全一致的假设情况）
    X_zero = np.zeros((1, X.shape[1]), dtype=float)
    return float(model.predict_proba(X_zero)[0, 1])


def retrieve_similar_windows(
    data: MarketData,
    end_indices: np.ndarray,
    features: np.ndarray,
    standardized_model_features: np.ndarray,
    primary_labels: list[str],
    current_probabilities: np.ndarray,
    current_regime: str,
    component_mapping: dict[int, str],
    window: int,
    horizon: int,
    top_n: int,
) -> list[dict[str, object]]:
    current_end = int(end_indices[-1])
    current_start = current_end - window + 1
    current_features_std = standardized_model_features[-1]
    current_path = z_path(data.close[current_start : current_end + 1])
    candidates: list[dict[str, object]] = []
    for row_index, candidate_end in enumerate(end_indices[:-1]):
        candidate_end = int(candidate_end)
        candidate_start = candidate_end - window + 1
        if candidate_end + horizon >= current_start:
            continue
        if not NO_REGIME_FILTER and primary_labels[row_index] != current_regime:
            continue
        candidate_path = z_path(data.close[candidate_start : candidate_end + 1])
        path_distance = float(np.sqrt(np.mean(np.square(current_path - candidate_path))))
        feature_distance = float(
            np.sqrt(np.mean(np.square(current_features_std - standardized_model_features[row_index])))
        )
        combined = PATH_WEIGHT * path_distance + FEATURE_WEIGHT * feature_distance
        candidates.append(
            {
                "row_index": row_index,
                "start_index": candidate_start,
                "end_index": candidate_end,
                "path_distance": path_distance,
                "feature_distance": feature_distance,
                "distance": combined,
            }
        )

    candidates.sort(key=lambda item: float(item["distance"]))
    selected: list[dict[str, object]] = []
    for candidate in candidates:
        candidate_end = int(candidate["end_index"])
        if any(windows_overlap(candidate_end, int(other["end_index"]), window) for other in selected):
            continue
        selected.append(candidate)
        if len(selected) >= top_n:
            break
    if len(selected) < min(3, top_n):
        if len(selected) == 0:
            raise ValueError("同类历史状态样本过少，无法形成稳定的预测区间。")
        # 允许少于 top_n 的结果

    distances = np.array([float(item["distance"]) for item in selected], dtype=float)
    scale = float(np.median(distances - distances.min()))
    if not math.isfinite(scale) or scale < 1e-6:
        scale = max(float(np.std(distances)), 0.10)
    weights = np.exp(-(distances - distances.min()) / scale)
    weights /= weights.sum()
    for rank, (item, weight) in enumerate(zip(selected, weights), 1):
        item["rank"] = rank
        item["weight"] = float(weight)
        start = int(item["start_index"])
        end = int(item["end_index"])
        item["start_date"] = data.dates[start]
        item["end_date"] = data.dates[end]
        item["similarity_score"] = float(100.0 * math.exp(-float(item["distance"])))
        item["window_return"] = float(data.close[end] / data.close[start] - 1.0)
        item["future_return"] = float(data.close[end + horizon] / data.close[end] - 1.0)
        item["future_path"] = np.array(
            [data.close[end + step] / data.close[end] - 1.0 for step in range(horizon + 1)],
            dtype=float,
        )
    return selected


def future_distribution(matches: list[dict[str, object]], horizon: int) -> list[dict[str, float]]:
    weights = np.array([float(item["weight"]) for item in matches], dtype=float)
    paths = np.vstack([np.asarray(item["future_path"], dtype=float) for item in matches])
    result: list[dict[str, float]] = []
    for step in range(horizon + 1):
        values = paths[:, step]
        result.append(
            {
                "step": float(step),
                "q10": weighted_quantile(values, 0.10, weights),
                "q20": weighted_quantile(values, 0.20, weights),
                "q25": weighted_quantile(values, 0.25, weights),
                "median": weighted_quantile(values, 0.50, weights),
                "q75": weighted_quantile(values, 0.75, weights),
                "q80": weighted_quantile(values, 0.80, weights),
                "q90": weighted_quantile(values, 0.90, weights),
                "weighted_mean": float(np.sum(values * weights)),
            }
        )
    return result


def bootstrap_mean_interval(matches: list[dict[str, object]], horizon: int, samples: int = 5000) -> tuple[float, float]:
    rng = np.random.default_rng(42)
    values = np.array([float(item["future_return"]) for item in matches], dtype=float)
    weights = np.array([float(item["weight"]) for item in matches], dtype=float)
    n = len(values)
    draws = rng.choice(np.arange(n), size=(samples, n), replace=True, p=weights)
    means = np.mean(values[draws], axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def plot_matches(data: MarketData, matches: list[dict[str, object]], window: int, output: Path) -> None:
    current_end = len(data.close) - 1
    current_start = current_end - window + 1
    x = np.arange(window)
    fig, axis = plt.subplots(figsize=(12, 6.5))
    axis.plot(x, z_path(data.close[current_start : current_end + 1]), linewidth=2.8, label="当前窗口")
    for item in matches[:5]:
        start = int(item["start_index"])
        end = int(item["end_index"])
        label = f"{item['rank']}. {data.dates[start]:%Y-%m-%d} 至 {data.dates[end]:%Y-%m-%d}"
        axis.plot(x, z_path(data.close[start : end + 1]), linewidth=1.25, alpha=0.78, label=label)
    axis.set_title("当前走势与历史相似市场阶段")
    axis.set_xlabel("窗口内数据点序号")
    axis.set_ylabel("标准化累计对数价格")
    axis.grid(alpha=0.22)
    axis.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_future(matches: list[dict[str, object]], distribution: list[dict[str, float]], output: Path) -> None:
    fig, axis = plt.subplots(figsize=(12, 6.5))
    for item in matches:
        path = np.asarray(item["future_path"], dtype=float) * 100.0
        axis.plot(np.arange(len(path)), path, linewidth=0.9, alpha=0.22)
    x = np.array([int(row["step"]) for row in distribution])
    median = np.array([row["median"] for row in distribution]) * 100.0
    q10 = np.array([row["q10"] for row in distribution]) * 100.0
    q90 = np.array([row["q90"] for row in distribution]) * 100.0
    q25 = np.array([row["q25"] for row in distribution]) * 100.0
    q75 = np.array([row["q75"] for row in distribution]) * 100.0
    axis.fill_between(x, q10, q90, alpha=0.12, label="80%经验预测区间")
    axis.fill_between(x, q25, q75, alpha=0.22, label="50%经验预测区间")
    axis.plot(x, median, linewidth=2.7, label="加权中位数")
    axis.axhline(0.0, linewidth=0.8)
    axis.set_title("历史相似阶段之后的收益分布")
    axis.set_xlabel("当前窗口结束后的数据点序号")
    axis.set_ylabel("相对窗口结束时收益（%）")
    axis.grid(alpha=0.22)
    axis.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)




def build_path_matrix(data: MarketData, end_indices: np.ndarray, window: int) -> np.ndarray:
    return np.vstack([
        z_path(data.close[int(end) - window + 1 : int(end) + 1])
        for end in end_indices
    ])


def retrieve_similar_windows_vectorized(
    data: MarketData,
    end_indices: np.ndarray,
    standardized_model_features: np.ndarray,
    path_matrix: np.ndarray,
    primary_labels: list[str],
    current_row: int,
    current_regime: str,
    window: int,
    horizon: int,
    top_n: int,
) -> list[dict[str, object]]:
    current_end = int(end_indices[current_row])
    current_start = current_end - window + 1
    row_numbers = np.arange(current_row, dtype=int)
    labels = np.asarray(primary_labels[:current_row], dtype=object)
    strict_mask = end_indices[:current_row] + horizon < current_start
    if NO_REGIME_FILTER:
        eligible_mask = strict_mask
    else:
        eligible_mask = strict_mask & (labels == current_regime)
    eligible = row_numbers[eligible_mask]
    if len(eligible) < min(3, top_n):
        if NO_REGIME_FILTER:
            raise ValueError(f"{window}期窗口历史样本总量不足（仅{len(eligible)}个）。")
        # 同类状态样本不足时，自动降级为全状态检索
        eligible_mask = strict_mask
        eligible = row_numbers[eligible_mask]
        if len(eligible) < min(3, top_n):
            raise ValueError(f"{window}期窗口历史样本总量不足（仅{len(eligible)}个）。")

    path_diff = path_matrix[eligible] - path_matrix[current_row]
    feature_diff = standardized_model_features[eligible] - standardized_model_features[current_row]
    path_distances = np.sqrt(np.mean(np.square(path_diff), axis=1))
    feature_distances = np.sqrt(np.mean(np.square(feature_diff), axis=1))
    combined_distances = PATH_WEIGHT * path_distances + FEATURE_WEIGHT * feature_distances
    order = np.argsort(combined_distances)

    selected: list[dict[str, object]] = []
    for position in order:
        row_index = int(eligible[position])
        candidate_end = int(end_indices[row_index])
        if any(windows_overlap(candidate_end, int(other["end_index"]), window) for other in selected):
            continue
        selected.append(
            {
                "row_index": row_index,
                "start_index": candidate_end - window + 1,
                "end_index": candidate_end,
                "path_distance": float(path_distances[position]),
                "feature_distance": float(feature_distances[position]),
                "distance": float(combined_distances[position]),
            }
        )
        if len(selected) >= top_n:
            break
    if len(selected) < min(3, top_n):
        if len(selected) == 0:
            raise ValueError(f"{window}期窗口互不重叠的历史样本不足。")
        # 允许少于 top_n 的结果，逻辑回归会处理小样本

    distances = np.array([float(item["distance"]) for item in selected], dtype=float)
    scale = float(np.median(distances - distances.min()))
    if not math.isfinite(scale) or scale < 1e-6:
        scale = max(float(np.std(distances)), 0.10)
    weights = np.exp(-(distances - distances.min()) / scale)
    weights /= weights.sum()
    for rank, (item, weight) in enumerate(zip(selected, weights), 1):
        item["rank"] = rank
        item["weight"] = float(weight)
        start = int(item["start_index"])
        end = int(item["end_index"])
        item["start_date"] = data.dates[start]
        item["end_date"] = data.dates[end]
        item["similarity_score"] = float(100.0 * math.exp(-float(item["distance"])))
        item["window_return"] = float(data.close[end] / data.close[start] - 1.0)
        item["future_return"] = float(data.close[end + horizon] / data.close[end] - 1.0)
        item["future_path"] = np.array(
            [data.close[end + step] / data.close[end] - 1.0 for step in range(horizon + 1)], dtype=float
        )
    return selected


def analyze_window_with_model(
    data: MarketData,
    end_indices_all: np.ndarray,
    features_all: np.ndarray,
    path_matrix_all: np.ndarray,
    evaluation_end: int,
    window: int,
    horizon: int,
    top_n: int,
    scaler: StandardScaler,
    gmm: GaussianMixture,
    mapping: dict[int, str],
) -> dict[str, object]:
    rows = int(np.searchsorted(end_indices_all, evaluation_end, side="right"))
    end_indices = end_indices_all[:rows]
    features = features_all[:rows]
    paths = path_matrix_all[:rows]
    if rows == 0 or int(end_indices[-1]) != evaluation_end:
        raise ValueError("评估日期没有对应完整窗口。")
    standardized = scaler.transform(features[:, MODEL_FEATURE_INDEX])
    posterior = gmm.predict_proba(standardized)
    component_labels = np.argmax(posterior, axis=1)
    primary_labels = [mapping[int(component)] for component in component_labels]
    current_row = rows - 1
    current_probs = aggregate_probabilities(posterior[current_row], mapping)
    current_regime = max(current_probs, key=current_probs.get)
    current_features = features[current_row]
    matches = retrieve_similar_windows_vectorized(
        data, end_indices, standardized, paths, primary_labels, current_row,
        current_regime, window, horizon, top_n
    )
    for item in matches:
        item["source_window"] = window
    distribution = future_distribution(matches, horizon)
    probability_up = logistic_direction_probability(matches)
    return {
        "window": window,
        "evaluation_end": evaluation_end,
        "probabilities": current_probs,
        "regime": current_regime,
        "stage": stage_description(current_regime, current_features),
        "features": current_features,
        "matches": matches,
        "distribution": distribution,
        "probability_up": probability_up,
        "probability_down": 1.0 - probability_up,
    }


REGIME_NAMES = ["上涨趋势", "下跌趋势", "低波动震荡", "高波动震荡"]


def parse_windows(text: str) -> list[int]:
    try:
        values = sorted({int(item.strip()) for item in text.split(",") if item.strip()})
    except ValueError as exc:
        raise ValueError("--windows 必须是逗号分隔的整数，例如 40,60,90。") from exc
    if not values or any(value < 20 for value in values):
        raise ValueError("每个窗口长度都必须至少为20。")
    return values


def slice_market_data(data: MarketData, end_index_inclusive: int) -> MarketData:
    stop = end_index_inclusive + 1
    return MarketData(
        dates=data.dates[:stop],
        open=data.open[:stop],
        high=data.high[:stop],
        low=data.low[:stop],
        close=data.close[:stop],
        source_name=data.source_name,
    )


def fit_gmm_state_model(
    model_features: np.ndarray,
    components: int,
    n_init: int,
) -> tuple[StandardScaler, GaussianMixture, np.ndarray, dict[int, str], list[str]]:
    if len(model_features) < max(components * 20, 150):
        raise ValueError("用于状态模型的历史窗口太少。")
    scaler = StandardScaler()
    standardized = scaler.fit_transform(model_features)
    gmm = GaussianMixture(
        n_components=components,
        covariance_type="full",
        random_state=42,
        n_init=n_init,
        reg_covar=1e-5,
        max_iter=300,
    )
    gmm.fit(standardized)
    posterior = gmm.predict_proba(standardized)
    mapping = map_components_to_regimes(gmm, scaler)
    component_labels = np.argmax(posterior, axis=1)
    primary_labels = [mapping[int(component)] for component in component_labels]
    return scaler, gmm, posterior, mapping, primary_labels


def retrieve_similar_windows_at(
    data: MarketData,
    end_indices: np.ndarray,
    standardized_model_features: np.ndarray,
    primary_labels: list[str],
    current_row: int,
    current_regime: str,
    window: int,
    horizon: int,
    top_n: int,
) -> list[dict[str, object]]:
    current_end = int(end_indices[current_row])
    current_start = current_end - window + 1
    current_features_std = standardized_model_features[current_row]
    current_path = z_path(data.close[current_start : current_end + 1])
    candidates: list[dict[str, object]] = []

    for row_index in range(current_row):
        candidate_end = int(end_indices[row_index])
        candidate_start = candidate_end - window + 1
        # 历史样本的未来观察期必须在当前窗口开始前结束，避免任何未来泄漏或窗口重叠。
        if candidate_end + horizon >= current_start:
            continue
        if not NO_REGIME_FILTER and primary_labels[row_index] != current_regime:
            continue
        candidate_path = z_path(data.close[candidate_start : candidate_end + 1])
        path_distance = float(np.sqrt(np.mean(np.square(current_path - candidate_path))))
        feature_distance = float(
            np.sqrt(np.mean(np.square(current_features_std - standardized_model_features[row_index])))
        )
        combined = PATH_WEIGHT * path_distance + FEATURE_WEIGHT * feature_distance
        candidates.append(
            {
                "row_index": row_index,
                "start_index": candidate_start,
                "end_index": candidate_end,
                "path_distance": path_distance,
                "feature_distance": feature_distance,
                "distance": combined,
            }
        )

    candidates.sort(key=lambda item: float(item["distance"]))
    selected: list[dict[str, object]] = []
    for candidate in candidates:
        candidate_end = int(candidate["end_index"])
        if any(windows_overlap(candidate_end, int(other["end_index"]), window) for other in selected):
            continue
        selected.append(candidate)
        if len(selected) >= top_n:
            break
    if len(selected) < min(3, top_n):
        if len(selected) == 0:
            raise ValueError(f"{window}期窗口的同类历史状态样本不足。")
        # 允许少于 top_n 的结果

    distances = np.array([float(item["distance"]) for item in selected], dtype=float)
    scale = float(np.median(distances - distances.min()))
    if not math.isfinite(scale) or scale < 1e-6:
        scale = max(float(np.std(distances)), 0.10)
    weights = np.exp(-(distances - distances.min()) / scale)
    weights /= weights.sum()

    for rank, (item, weight) in enumerate(zip(selected, weights), 1):
        item["rank"] = rank
        item["weight"] = float(weight)
        start = int(item["start_index"])
        end = int(item["end_index"])
        item["start_date"] = data.dates[start]
        item["end_date"] = data.dates[end]
        item["similarity_score"] = float(100.0 * math.exp(-float(item["distance"])))
        item["window_return"] = float(data.close[end] / data.close[start] - 1.0)
        item["future_return"] = float(data.close[end + horizon] / data.close[end] - 1.0)
        item["future_path"] = np.array(
            [data.close[end + step] / data.close[end] - 1.0 for step in range(horizon + 1)],
            dtype=float,
        )
    return selected


def analyze_window_at(
    data: MarketData,
    end_indices_all: np.ndarray,
    features_all: np.ndarray,
    evaluation_end: int,
    window: int,
    horizon: int,
    top_n: int,
    components: int,
    n_init: int,
) -> dict[str, object]:
    rows = int(np.searchsorted(end_indices_all, evaluation_end, side="right"))
    if rows < max(components * 20, 150):
        raise ValueError(f"{window}期窗口在该日期前的训练数据不足。")
    end_indices = end_indices_all[:rows]
    features = features_all[:rows]
    if int(end_indices[-1]) != evaluation_end:
        raise ValueError("评估日期没有对应完整窗口。")

    model_features = features[:, MODEL_FEATURE_INDEX]
    scaler, gmm, posterior, mapping, primary_labels = fit_gmm_state_model(
        model_features, components=components, n_init=n_init
    )
    standardized = scaler.transform(model_features)
    current_row = len(end_indices) - 1
    current_probs = aggregate_probabilities(posterior[current_row], mapping)
    current_regime = max(current_probs, key=current_probs.get)
    current_features = features[current_row]
    matches = retrieve_similar_windows_at(
        data=data,
        end_indices=end_indices,
        standardized_model_features=standardized,
        primary_labels=primary_labels,
        current_row=current_row,
        current_regime=current_regime,
        window=window,
        horizon=horizon,
        top_n=top_n,
    )
    for item in matches:
        item["source_window"] = window
    distribution = future_distribution(matches, horizon)
    probability_up = logistic_direction_probability(matches)
    return {
        "window": window,
        "evaluation_end": evaluation_end,
        "probabilities": current_probs,
        "regime": current_regime,
        "stage": stage_description(current_regime, current_features),
        "features": current_features,
        "matches": matches,
        "distribution": distribution,
        "probability_up": probability_up,
        "probability_down": 1.0 - probability_up,
    }


def ensemble_state(window_results: list[dict[str, object]]) -> dict[str, object]:
    if not window_results:
        raise ValueError("没有可用于集成的窗口结果。")
    probabilities = {
        regime: float(np.mean([float(result["probabilities"][regime]) for result in window_results]))
        for regime in REGIME_NAMES
    }
    dominant = max(probabilities, key=probabilities.get)
    window_dominants = [str(result["regime"]) for result in window_results]
    agreement = float(np.mean([label == dominant for label in window_dominants]))
    sideways_probability = probabilities["低波动震荡"] + probabilities["高波动震荡"]
    trend_probability = probabilities["上涨趋势"] + probabilities["下跌趋势"]

    unique = set(window_dominants)
    if len(unique) == 1:
        interpretation = f"多窗口一致判断为{dominant}"
    elif dominant in {"上涨趋势", "下跌趋势"} and any("震荡" in label for label in unique):
        interpretation = f"{dominant}占优，但不同窗口对趋势与震荡存在分歧，可能处于状态转换期"
    elif "上涨趋势" in unique and "下跌趋势" in unique:
        interpretation = "短中长期方向明显冲突，当前状态不稳定"
    else:
        interpretation = f"集成判断偏向{dominant}，但窗口间存在分歧"

    return {
        "probabilities": probabilities,
        "dominant_regime": dominant,
        "agreement": agreement,
        "sideways_probability": sideways_probability,
        "trend_probability": trend_probability,
        "interpretation": interpretation,
    }


def combine_window_matches(window_results: list[dict[str, object]], horizon: int) -> tuple[list[dict[str, object]], list[dict[str, float]]]:
    successful = len(window_results)
    grouped: dict[int, dict[str, object]] = {}
    for result in window_results:
        window = int(result["window"])
        for item in result["matches"]:
            end = int(item["end_index"])
            contribution = float(item["weight"]) / successful
            if end not in grouped:
                grouped[end] = {
                    "end_index": end,
                    "start_index": int(item["start_index"]),
                    "start_date": item["start_date"],
                    "end_date": item["end_date"],
                    "future_return": float(item["future_return"]),
                    "future_path": np.asarray(item["future_path"], dtype=float),
                    "ensemble_weight": 0.0,
                    "source_windows": [],
                    "best_similarity": float(item["similarity_score"]),
                }
            group = grouped[end]
            group["ensemble_weight"] = float(group["ensemble_weight"]) + contribution
            group["source_windows"].append(window)
            group["start_index"] = min(int(group["start_index"]), int(item["start_index"]))
            group["start_date"] = min(group["start_date"], item["start_date"])
            group["best_similarity"] = max(float(group["best_similarity"]), float(item["similarity_score"]))

    combined = list(grouped.values())
    total = sum(float(item["ensemble_weight"]) for item in combined)
    if total <= 0:
        raise ValueError("集成历史样本权重无效。")
    for item in combined:
        item["weight"] = float(item["ensemble_weight"]) / total
        item["source_windows"] = sorted(set(item["source_windows"]))
    combined.sort(key=lambda item: float(item["weight"]), reverse=True)
    for rank, item in enumerate(combined, 1):
        item["rank"] = rank
    return combined, future_distribution(combined, horizon)


def prediction_from_combined(matches: list[dict[str, object]], distribution: list[dict[str, float]]) -> dict[str, float]:
    weights = np.array([float(item["weight"]) for item in matches], dtype=float)
    last = distribution[-1]
    return {
        "probability_up_raw": float(sum(float(item["weight"]) for item in matches if float(item["future_return"]) > 0)),
        "probability_down_raw": float(sum(float(item["weight"]) for item in matches if float(item["future_return"]) < 0)),
        "mean": float(last["weighted_mean"]),
        "median": float(last["median"]),
        "q25": float(last["q25"]),
        "q75": float(last["q75"]),
        "q10": float(last["q10"]),
        "q90": float(last["q90"]),
        "effective_sample_size": float(1.0 / np.sum(np.square(weights))),
    }


def expanding_isotonic_predictions(raw_probabilities: np.ndarray, outcomes: np.ndarray, min_history: int = 30) -> np.ndarray:
    calibrated = np.full(len(raw_probabilities), np.nan, dtype=float)
    for index in range(min_history, len(raw_probabilities)):
        x = raw_probabilities[:index]
        y = outcomes[:index]
        if len(np.unique(y)) < 2 or len(np.unique(x)) < 3:
            calibrated[index] = float(np.mean(y))
            continue
        model = IsotonicRegression(out_of_bounds="clip", y_min=0.02, y_max=0.98)
        model.fit(x, y)
        calibrated[index] = float(model.predict([raw_probabilities[index]])[0])
    return calibrated


def fit_current_probability_calibrator(raw_probabilities: np.ndarray, outcomes: np.ndarray, current_raw: float) -> float | None:
    if len(raw_probabilities) < 30 or len(np.unique(outcomes)) < 2 or len(np.unique(raw_probabilities)) < 3:
        return None
    model = IsotonicRegression(out_of_bounds="clip", y_min=0.02, y_max=0.98)
    model.fit(raw_probabilities, outcomes)
    return float(model.predict([current_raw])[0])


def probability_calibration_rows(probabilities: np.ndarray, outcomes: np.ndarray) -> list[list[object]]:
    bins = np.linspace(0.0, 1.0, 6)
    rows: list[list[object]] = []
    for lower, upper in zip(bins[:-1], bins[1:]):
        if upper == 1.0:
            mask = (probabilities >= lower) & (probabilities <= upper)
        else:
            mask = (probabilities >= lower) & (probabilities < upper)
        count = int(mask.sum())
        rows.append(
            [
                lower,
                upper,
                count,
                float(np.mean(probabilities[mask])) if count else math.nan,
                float(np.mean(outcomes[mask])) if count else math.nan,
            ]
        )
    return rows


def safe_log_loss(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    p = np.clip(probabilities, 1e-6, 1 - 1e-6)
    return float(-np.mean(outcomes * np.log(p) + (1 - outcomes) * np.log(1 - p)))


def run_walk_forward_backtest(
    data: MarketData,
    feature_cache: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]],
    windows: list[int],
    horizon: int,
    top_n: int,
    components: int,
    backtest_start: datetime,
    step: int,
    refit_step: int,
    n_init: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    first_by_date = int(np.searchsorted(data.dates, backtest_start, side="left"))
    first_evaluation = max(first_by_date, max(windows) - 1 + 500)
    last_evaluation = len(data.close) - horizon - 1
    evaluation_indices = list(range(first_evaluation, last_evaluation + 1, step))
    records: list[dict[str, object]] = []
    model_cache: dict[int, dict[str, object]] = {}

    for counter, evaluation_end in enumerate(evaluation_indices, 1):
        per_window: list[dict[str, object]] = []
        for window in windows:
            end_indices, features, path_matrix = feature_cache[window]
            cached = model_cache.get(window)
            needs_refit = cached is None or evaluation_end - int(cached["fit_end"]) >= refit_step
            if needs_refit:
                rows = int(np.searchsorted(end_indices, evaluation_end, side="right"))
                training_features = features[:rows, MODEL_FEATURE_INDEX]
                try:
                    scaler, gmm, _posterior, mapping, _labels = fit_gmm_state_model(
                        training_features, components=components, n_init=n_init
                    )
                except ValueError:
                    continue
                cached = {
                    "fit_end": evaluation_end,
                    "scaler": scaler,
                    "gmm": gmm,
                    "mapping": mapping,
                }
                model_cache[window] = cached
            try:
                result = analyze_window_with_model(
                    data=data,
                    end_indices_all=end_indices,
                    features_all=features,
                    path_matrix_all=path_matrix,
                    evaluation_end=evaluation_end,
                    window=window,
                    horizon=horizon,
                    top_n=top_n,
                    scaler=cached["scaler"],
                    gmm=cached["gmm"],
                    mapping=cached["mapping"],
                )
                per_window.append(result)
            except ValueError:
                continue
        if len(per_window) < max(1, math.ceil(len(windows) / 2)):
            continue
        state = ensemble_state(per_window)
        combined_matches, combined_distribution = combine_window_matches(per_window, horizon)
        prediction = prediction_from_combined(combined_matches, combined_distribution)
        # 多窗口逻辑回归概率取平均，替代集成加权计数
        logistic_probs = [float(r["probability_up"]) for r in per_window]
        ensemble_logistic_prob = float(np.mean(logistic_probs))
        actual_return = float(data.close[evaluation_end + horizon] / data.close[evaluation_end] - 1.0)
        records.append(
            {
                "date": data.dates[evaluation_end],
                "evaluation_end": evaluation_end,
                "windows_used": [int(result["window"]) for result in per_window],
                "dominant_regime": state["dominant_regime"],
                "state_agreement": state["agreement"],
                "sideways_probability": state["sideways_probability"],
                "probability_up_raw": ensemble_logistic_prob,
                "predicted_median": prediction["median"],
                "q25": prediction["q25"],
                "q75": prediction["q75"],
                "q10": prediction["q10"],
                "q90": prediction["q90"],
                "actual_return": actual_return,
                "actual_up": 1.0 if actual_return > 0 else 0.0,
            }
        )
        if counter % 50 == 0:
            print(f"walk-forward进度：{counter}/{len(evaluation_indices)} 个评估日期", flush=True)

    if len(records) < 30:
        raise ValueError("walk-forward有效评估点少于30个，无法进行概率校准。")

    raw = np.array([float(row["probability_up_raw"]) for row in records], dtype=float)
    outcomes = np.array([float(row["actual_up"]) for row in records], dtype=float)
    calibrated = expanding_isotonic_predictions(raw, outcomes, min_history=30)
    for row, probability in zip(records, calibrated):
        row["probability_up_calibrated"] = float(probability) if math.isfinite(probability) else math.nan

    actual_returns = np.array([float(row["actual_return"]) for row in records], dtype=float)
    medians = np.array([float(row["predicted_median"]) for row in records], dtype=float)
    q25 = np.array([float(row["q25"]) for row in records], dtype=float)
    q75 = np.array([float(row["q75"]) for row in records], dtype=float)
    q10 = np.array([float(row["q10"]) for row in records], dtype=float)
    q90 = np.array([float(row["q90"]) for row in records], dtype=float)
    calibrated_mask = np.isfinite(calibrated)

    raw_accuracy = float(np.mean((raw >= 0.5) == (outcomes == 1)))
    raw_brier = float(np.mean(np.square(raw - outcomes)))
    raw_log_loss = safe_log_loss(raw, outcomes)
    base_rate = float(np.mean(outcomes))
    baseline_accuracy = max(base_rate, 1.0 - base_rate)
    baseline_probabilities = np.full_like(outcomes, base_rate, dtype=float)
    baseline_brier = float(np.mean(np.square(baseline_probabilities - outcomes)))
    baseline_log_loss = safe_log_loss(baseline_probabilities, outcomes)
    brier_skill = float(1.0 - raw_brier / baseline_brier) if baseline_brier > 0 else math.nan
    raw_passed = bool(raw_brier < baseline_brier and raw_log_loss < baseline_log_loss)

    summary: dict[str, object] = {
        "评估点数量": len(records),
        "评估日期范围": [records[0]["date"].strftime("%Y-%m-%d"), records[-1]["date"].strftime("%Y-%m-%d")],
        "评估步长": step,
        "状态模型重新拟合步长": refit_step,
        "预测周期": horizon,
        "历史实际上涨比例": base_rate,
        "多数类方向基准准确率": baseline_accuracy,
        "无条件概率基准Brier分数": baseline_brier,
        "无条件概率基准对数损失": baseline_log_loss,
        "原始方向准确率": raw_accuracy,
        "原始Brier分数": raw_brier,
        "原始对数损失": raw_log_loss,
        "相对基准Brier技能分数": brier_skill,
        "原始方向模型是否通过基准": raw_passed,
        "收益中位数MAE": float(np.mean(np.abs(medians - actual_returns))),
        "50%预测区间覆盖率": float(np.mean((actual_returns >= q25) & (actual_returns <= q75))),
        "80%预测区间覆盖率": float(np.mean((actual_returns >= q10) & (actual_returns <= q90))),
        "平均50%区间宽度": float(np.mean(q75 - q25)),
        "平均80%区间宽度": float(np.mean(q90 - q10)),
    }
    if calibrated_mask.any():
        calibrated_accuracy = float(np.mean((calibrated[calibrated_mask] >= 0.5) == (outcomes[calibrated_mask] == 1)))
        calibrated_brier = float(np.mean(np.square(calibrated[calibrated_mask] - outcomes[calibrated_mask])))
        calibrated_log_loss = safe_log_loss(calibrated[calibrated_mask], outcomes[calibrated_mask])
        calibrated_passed = bool(calibrated_brier < raw_brier and calibrated_brier < baseline_brier)
        summary.update(
            {
                "严格滚动校准评估点": int(calibrated_mask.sum()),
                "校准后方向准确率": calibrated_accuracy,
                "校准后Brier分数": calibrated_brier,
                "校准后对数损失": calibrated_log_loss,
                "校准模型是否优于原始及基准": calibrated_passed,
            }
        )
    return records, summary

def plot_calibration(rows: list[list[object]], output: Path, title: str) -> None:
    valid = [row for row in rows if int(row[2]) > 0 and math.isfinite(float(row[3])) and math.isfinite(float(row[4]))]
    if not valid:
        return
    x = np.array([float(row[3]) for row in valid])
    y = np.array([float(row[4]) for row in valid])
    fig, axis = plt.subplots(figsize=(7, 6))
    axis.plot([0, 1], [0, 1], linestyle="--", linewidth=1.0, label="理想校准")
    axis.plot(x, y, marker="o", linewidth=2.0, label="实际上涨频率")
    for row, px, py in zip(valid, x, y):
        axis.annotate(f"n={int(row[2])}", (px, py), xytext=(4, 5), textcoords="offset points", fontsize=8)
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.set_xlabel("模型给出的上涨概率")
    axis.set_ylabel("实际上涨频率")
    axis.set_title(title)
    axis.grid(alpha=0.22)
    axis.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)



def clean_terminal_path(raw: str) -> Path:
    """清理从 Finder 拖入终端后产生的引号和转义空格。"""
    value = raw.strip().strip("\"").strip("'")
    value = value.replace("\\ ", " ")
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def prompt_text(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    raw = input(f"{message}{suffix}: ").strip()
    return raw if raw else (default or "")


def prompt_integer(message: str, default: int, minimum: int = 1) -> int:
    while True:
        raw = input(f"{message} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("请输入整数。")
            continue
        if value < minimum:
            print(f"数值必须至少为 {minimum}。")
            continue
        return value


def prompt_yes_no(message: str, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{message} [{marker}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes", "是", "1"}:
            return True
        if raw in {"n", "no", "否", "0"}:
            return False
        print("请输入 y 或 n。")


def configure_interactively(args: argparse.Namespace) -> argparse.Namespace:
    print("\n" + "=" * 58)
    print("市场状态识别与历史相似阶段分析｜交互模式")
    print("=" * 58)
    print("可把 Excel/CSV 文件直接从 Finder 拖入终端，然后按回车。")

    while True:
        raw_path = input("\n请输入数据文件路径: ").strip()
        if not raw_path:
            print("文件路径不能为空。")
            continue
        candidate = clean_terminal_path(raw_path)
        if not candidate.exists():
            print(f"找不到文件：{candidate}")
            continue
        if candidate.suffix.lower() not in {".xlsx", ".csv"}:
            print("目前只支持 .xlsx 和 .csv。")
            continue
        args.input = candidate
        break

    print("\n请选择运行方式：")
    print("  1. 快速分析：当前状态 + 历史相似阶段（推荐先运行）")
    print("  2. 完整分析：快速分析 + walk-forward 历史回测")
    while True:
        mode = prompt_text("输入编号", "1")
        if mode in {"1", "2"}:
            break
        print("请输入 1 或 2。")
    args.backtest = mode == "2"

    args.windows = prompt_text("集成窗口，用逗号分隔", str(args.windows))
    args.horizon = prompt_integer("分析未来多少个数据点", int(args.horizon), 1)
    suggested_top_n = 20 if args.backtest else int(args.top_n)
    args.top_n = prompt_integer("每个窗口使用多少个历史相似样本", 60, 5)
    args.no_regime_filter = prompt_yes_no("是否取消同类GMM状态过滤（检索所有状态，增加样本量）", True)
    args.start_date = prompt_text("建模起始日期 YYYY-MM-DD", str(args.start_date))
    while True:
        raw_pw = prompt_text("价格形状权重0-1；市场特征自动为1减去它", str(args.path_weight))
        try:
            args.path_weight = float(raw_pw)
        except ValueError:
            print("请输入0到1之间的数字。")
            continue
        if 0.0 <= args.path_weight <= 1.0:
            break
        print("请输入0到1之间的数字。")

    default_output = args.input.parent / f"市场状态分析结果_{datetime.now():%Y%m%d_%H%M%S}"
    output_raw = prompt_text("结果保存文件夹；留空使用默认位置", "")
    args.output = clean_terminal_path(output_raw) if output_raw else default_output

    if args.backtest:
        print("\n回测参数通常可以直接按回车使用默认值。")
        args.backtest_start = prompt_text("回测开始日期 YYYY-MM-DD", str(args.backtest_start))
        args.backtest_step = prompt_integer("每隔多少个数据点评估一次", int(args.backtest_step), 1)
        args.backtest_refit_step = prompt_integer(
            "状态模型每隔多少个数据点重新拟合", int(args.backtest_refit_step), 1
        )
        args.backtest_n_init = prompt_integer("回测时 GMM 初始化次数", int(args.backtest_n_init), 1)

    print("\n即将运行：")
    print(f"  数据文件：{args.input}")
    print(f"  窗口：{args.windows}")
    print(f"  未来长度：{args.horizon}")
    print(f"  相似样本：{args.top_n}")
    print(f"  跨状态检索：{'是' if args.no_regime_filter else '否（仅同类状态）'}")
    print(f"  完整回测：{'是' if args.backtest else '否'}")
    print(f"  输出目录：{args.output}")
    if not prompt_yes_no("确认开始", True):
        print("已取消。")
        raise SystemExit(0)
    return args

def main() -> int:
    parser = argparse.ArgumentParser(description="多窗口市场状态识别、历史相似检索与walk-forward回测")
    parser.add_argument("input", nargs="?", type=Path, help="输入 .xlsx 或 .csv 文件；省略则进入交互模式")
    parser.add_argument("--interactive", action="store_true", help="强制进入交互模式")
    parser.add_argument("--windows", default="40,60,90", help="集成窗口，例如40,60,90")
    parser.add_argument("--horizon", type=int, default=10, help="未来分析长度，默认10")
    parser.add_argument("--top-n", type=int, default=60, help="每个窗口历史相似样本数，默认60")
    parser.add_argument("--components", type=int, default=5, help="GMM成分数，默认5")
    parser.add_argument("--path-weight", type=float, default=0.55, help="历史相似度中价格形状权重，0到1；市场特征权重自动为1减去它")
    parser.add_argument("--no-regime-filter", action="store_true", help="取消同类GMM状态过滤，允许在所有历史状态中检索，显著增加候选样本量")
    parser.add_argument("--start-date", default="1980-01-01", help="建模起始日期，默认1980-01-01")
    parser.add_argument("--output", type=Path, default=None, help="结果目录")
    parser.add_argument("--backtest", action="store_true", help="运行严格walk-forward回测")
    parser.add_argument("--backtest-start", default="2000-01-01", help="回测开始日期，默认2000-01-01")
    parser.add_argument("--backtest-step", type=int, default=20, help="每隔多少个数据点评估一次，默认20")
    parser.add_argument("--backtest-refit-step", type=int, default=126, help="状态模型每隔多少个数据点重新拟合，默认126")
    parser.add_argument("--backtest-n-init", type=int, default=2, help="回测每次GMM初始化次数，默认2")
    args = parser.parse_args()
    if args.interactive or args.input is None:
        args = configure_interactively(args)
    else:
        args.input = clean_terminal_path(str(args.input))

    if not 0.0 <= args.path_weight <= 1.0:
        raise ValueError("--path-weight 必须在0到1之间。")
    global PATH_WEIGHT, FEATURE_WEIGHT, NO_REGIME_FILTER
    PATH_WEIGHT = float(args.path_weight)
    FEATURE_WEIGHT = 1.0 - PATH_WEIGHT
    NO_REGIME_FILTER = bool(args.no_regime_filter)
    print(f"历史相似度权重：价格形状 {PATH_WEIGHT:.1%}｜市场特征 {FEATURE_WEIGHT:.1%}")
    if NO_REGIME_FILTER:
        print("⚠️ 已取消同类状态过滤，将检索所有历史状态中的相似窗口（样本量更大）。")

    windows = parse_windows(args.windows)
    if args.horizon < 1:
        raise ValueError("未来分析长度必须至少为1。")
    if args.top_n < 5:
        raise ValueError("历史相似样本建议至少5个。")
    if args.backtest_step < 1:
        raise ValueError("回测步长必须至少为1。")
    if args.backtest_refit_step < 1:
        raise ValueError("状态模型重新拟合步长必须至少为1。")

    configure_chinese_font()
    raw_data = load_market_data(args.input.resolve())
    data = subset_from_date(raw_data, datetime.strptime(args.start_date, "%Y-%m-%d"))
    if len(data.close) < max(windows) + args.horizon + 500:
        raise ValueError("可用数据不足以完成多窗口建模。")

    output = args.output or args.input.resolve().parent / f"市场状态集成结果_{datetime.now():%Y%m%d_%H%M%S}"
    output.mkdir(parents=True, exist_ok=True)

    print("正在预计算各窗口特征……", flush=True)
    feature_cache = {}
    for window in windows:
        end_indices, features = build_feature_matrix(data, window)
        feature_cache[window] = (end_indices, features, build_path_matrix(data, end_indices, window))
    current_end = len(data.close) - 1
    current_window_results: list[dict[str, object]] = []
    for window in windows:
        end_indices, features, path_matrix = feature_cache[window]
        rows = int(np.searchsorted(end_indices, current_end, side="right"))
        scaler, gmm, _posterior, mapping, _labels = fit_gmm_state_model(
            features[:rows, MODEL_FEATURE_INDEX], components=args.components, n_init=10
        )
        result = analyze_window_with_model(
            data=data,
            end_indices_all=end_indices,
            features_all=features,
            path_matrix_all=path_matrix,
            evaluation_end=current_end,
            window=window,
            horizon=args.horizon,
            top_n=args.top_n,
            scaler=scaler,
            gmm=gmm,
            mapping=mapping,
        )
        current_window_results.append(result)

    current_state = ensemble_state(current_window_results)
    combined_matches, combined_distribution = combine_window_matches(current_window_results, args.horizon)
    current_prediction = prediction_from_combined(combined_matches, combined_distribution)
    # 多窗口逻辑回归概率取平均
    logistic_probs = [float(r["probability_up"]) for r in current_window_results]
    current_prediction["probability_up_raw"] = float(np.mean(logistic_probs))

    backtest_records: list[dict[str, object]] = []
    backtest_summary: dict[str, object] | None = None
    current_calibrated_probability: float | None = None
    diagnostic_calibrated_probability: float | None = None
    if args.backtest:
        print("开始严格walk-forward回测；每个评估点只使用当时之前的数据……", flush=True)
        backtest_records, backtest_summary = run_walk_forward_backtest(
            data=data,
            feature_cache=feature_cache,
            windows=windows,
            horizon=args.horizon,
            top_n=args.top_n,
            components=args.components,
            backtest_start=datetime.strptime(args.backtest_start, "%Y-%m-%d"),
            step=args.backtest_step,
            refit_step=args.backtest_refit_step,
            n_init=args.backtest_n_init,
        )
        raw_probs = np.array([float(row["probability_up_raw"]) for row in backtest_records], dtype=float)
        outcomes = np.array([float(row["actual_up"]) for row in backtest_records], dtype=float)
        diagnostic_calibrated_probability = fit_current_probability_calibrator(
            raw_probs, outcomes, float(current_prediction["probability_up_raw"])
        )
        if bool(backtest_summary.get("校准模型是否优于原始及基准", False)):
            current_calibrated_probability = diagnostic_calibrated_probability

        backtest_rows = []
        for row in backtest_records:
            backtest_rows.append(
                [
                    row["date"].strftime("%Y-%m-%d"),
                    ",".join(map(str, row["windows_used"])),
                    row["dominant_regime"],
                    row["state_agreement"],
                    row["sideways_probability"],
                    row["probability_up_raw"],
                    row["probability_up_calibrated"],
                    row["predicted_median"],
                    row["q25"],
                    row["q75"],
                    row["q10"],
                    row["q90"],
                    row["actual_return"],
                    row["actual_up"],
                ]
            )
        write_csv(
            output / "walk_forward逐期结果.csv",
            [
                "评估日期", "使用窗口", "集成状态", "状态一致率", "震荡概率", "原始上涨概率", "严格滚动校准上涨概率",
                "预测中位数收益", "50%下限", "50%上限", "80%下限", "80%上限", "实际未来收益", "实际是否上涨",
            ],
            backtest_rows,
        )
        (output / "walk_forward回测摘要.json").write_text(
            json.dumps(backtest_summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raw_calibration = probability_calibration_rows(raw_probs, outcomes)
        write_csv(
            output / "原始概率校准表.csv",
            ["概率区间下限", "概率区间上限", "样本数", "平均预测概率", "实际上涨频率"],
            raw_calibration,
        )
        plot_calibration(raw_calibration, output / "原始概率校准图.png", "walk-forward原始上涨概率校准")

        calibrated = np.array([float(row["probability_up_calibrated"]) for row in backtest_records], dtype=float)
        mask = np.isfinite(calibrated)
        if mask.any():
            calibrated_rows = probability_calibration_rows(calibrated[mask], outcomes[mask])
            write_csv(
                output / "严格滚动校准表.csv",
                ["概率区间下限", "概率区间上限", "样本数", "平均预测概率", "实际上涨频率"],
                calibrated_rows,
            )
            plot_calibration(calibrated_rows, output / "严格滚动校准图.png", "严格滚动校准后的上涨概率")

    window_rows: list[list[object]] = []
    for result in current_window_results:
        probabilities = result["probabilities"]
        final_distribution = result["distribution"][-1]
        window_rows.append(
            [
                result["window"],
                result["regime"],
                result["stage"],
                probabilities["上涨趋势"],
                probabilities["下跌趋势"],
                probabilities["低波动震荡"],
                probabilities["高波动震荡"],
                probabilities["低波动震荡"] + probabilities["高波动震荡"],
                result["probability_up"],
                final_distribution["median"],
                final_distribution["q10"],
                final_distribution["q90"],
            ]
        )
    write_csv(
        output / "当前多窗口分析.csv",
        [
            "窗口", "主要状态", "阶段", "上涨趋势概率", "下跌趋势概率", "低波动震荡概率", "高波动震荡概率",
            "震荡合计概率", f"未来{args.horizon}期原始上涨概率", "未来收益中位数", "80%下限", "80%上限",
        ],
        window_rows,
    )

    match_rows: list[list[object]] = []
    for item in combined_matches:
        match_rows.append(
            [
                item["rank"],
                item["start_date"].strftime("%Y-%m-%d"),
                item["end_date"].strftime("%Y-%m-%d"),
                ",".join(map(str, item["source_windows"])),
                item["best_similarity"],
                item["weight"],
                item["future_return"],
            ]
        )
    write_csv(
        output / "集成历史相似阶段.csv",
        ["排名", "开始日期", "结束日期", "来源窗口", "最佳相似度", "集成权重", f"随后{args.horizon}期收益"],
        match_rows,
    )
    write_csv(
        output / "集成未来收益分布.csv",
        ["未来数据点", "加权均值", "加权中位数", "50%下限", "50%上限", "80%下限", "80%上限"],
        [
            [int(row["step"]), row["weighted_mean"], row["median"], row["q25"], row["q75"], row["q10"], row["q90"]]
            for row in combined_distribution
        ],
    )
    plot_future(combined_matches, combined_distribution, output / "集成历史相似阶段后续走势.png")

    current_result = {
        "数据文件": data.source_name,
        "原始数据范围": [raw_data.dates[0].strftime("%Y-%m-%d"), raw_data.dates[-1].strftime("%Y-%m-%d")],
        "建模数据范围": [data.dates[0].strftime("%Y-%m-%d"), data.dates[-1].strftime("%Y-%m-%d")],
        "当前日期": data.dates[-1].strftime("%Y-%m-%d"),
        "集成窗口": windows,
        "集成主要状态": current_state["dominant_regime"],
        "集成状态概率": current_state["probabilities"],
        "震荡合计概率": current_state["sideways_probability"],
        "窗口状态一致率": current_state["agreement"],
        "状态解释": current_state["interpretation"],
        f"未来{args.horizon}期原始上涨概率": current_prediction["probability_up_raw"],
        f"未来{args.horizon}期通过基准检验后的校准上涨概率": current_calibrated_probability,
        f"未来{args.horizon}期诊断性校准值": diagnostic_calibrated_probability,
        "方向预测是否通过基准检验": (
            None if backtest_summary is None
            else bool(backtest_summary.get("原始方向模型是否通过基准", False))
        ),
        f"未来{args.horizon}期收益中位数": current_prediction["median"],
        f"未来{args.horizon}期50%经验预测区间": [current_prediction["q25"], current_prediction["q75"]],
        f"未来{args.horizon}期80%经验预测区间": [current_prediction["q10"], current_prediction["q90"]],
        "集成有效样本量": current_prediction["effective_sample_size"],
        "各窗口": [
            {
                "窗口": result["window"],
                "状态": result["regime"],
                "阶段": result["stage"],
                "状态概率": result["probabilities"],
                f"未来{args.horizon}期原始上涨概率": result["probability_up"],
            }
            for result in current_window_results
        ],
        "walk_forward回测摘要": backtest_summary,
    }
    (output / "当前集成判断.json").write_text(
        json.dumps(current_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary_lines = [
        "多窗口市场状态集成与walk-forward检验",
        "=" * 42,
        f"数据：{data.source_name}",
        f"建模范围：{data.dates[0]:%Y-%m-%d} 至 {data.dates[-1]:%Y-%m-%d}",
        f"集成窗口：{', '.join(map(str, windows))}期",
        "",
        f"当前集成状态：{current_state['dominant_regime']}",
        f"震荡合计概率：{current_state['sideways_probability']:.2%}",
        f"窗口状态一致率：{current_state['agreement']:.2%}",
        f"解释：{current_state['interpretation']}",
        "集成状态概率：",
        *[f"  - {key}：{value:.2%}" for key, value in sorted(current_state["probabilities"].items(), key=lambda kv: kv[1], reverse=True)],
        "",
        f"未来{args.horizon}期原始历史上涨概率：{current_prediction['probability_up_raw']:.2%}",
        (
            f"未来{args.horizon}期通过基准检验后的校准上涨概率：{current_calibrated_probability:.2%}"
            if current_calibrated_probability is not None
            else (
                "本次未运行walk-forward回测，因此不提供经过检验的校准上涨概率"
                if backtest_summary is None
                else "方向预测未通过历史基准检验，因此不提供可操作的校准上涨概率"
            )
        ),
        f"未来{args.horizon}期收益中位数：{current_prediction['median']:.2%}",
        f"未来{args.horizon}期50%经验预测区间：{current_prediction['q25']:.2%} 至 {current_prediction['q75']:.2%}",
        f"未来{args.horizon}期80%经验预测区间：{current_prediction['q10']:.2%} 至 {current_prediction['q90']:.2%}",
        f"集成有效样本量：{current_prediction['effective_sample_size']:.2f}",
    ]
    if backtest_summary is not None:
        summary_lines.extend(
            [
                "",
                "walk-forward回测：",
                *[f"  - {key}：{value:.4f}" if isinstance(value, float) else f"  - {key}：{value}" for key, value in backtest_summary.items()],
            ]
        )
    summary_lines.extend(
        [
            "",
            "注意：状态概率仍是无监督模型归属度；未来上涨概率只有在walk-forward表现优于无条件基准时才可作为有效信号。",
            "walk-forward中每个评估点只使用当时及之前的数据，历史匹配样本的未来观察期也必须在当前窗口开始前结束。",
        ]
    )
    (output / "分析摘要.txt").write_text("\n".join(summary_lines), encoding="utf-8")
    print("\n".join(summary_lines))
    print(f"\n结果已保存至：{output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"\n运行出错：{exc}", file=sys.stderr)
        raise SystemExit(1)
