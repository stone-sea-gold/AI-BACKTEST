"""指标规格定义层。不做数值计算，仅定义指标参数和 SQL 模板。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class IndicatorSpec:
    """指标规格定义。"""
    name: str
    params: list[tuple[str, type]] = field(default_factory=list)
    sql_template: str = ""
    dependencies: list[str] = field(default_factory=list)
    validator: Callable | None = None


def _validate_positive_window(params: dict):
    w = params.get("window", 0)
    if w < 1:
        raise ValueError(f"window 必须 >= 1, got {w}")


def _validate_macd_params(params: dict):
    fast = params.get("fast", 12)
    slow = params.get("slow", 26)
    signal = params.get("signal", 9)
    if fast >= slow:
        raise ValueError(f"MACD fast({fast}) 必须 < slow({slow})")
    if signal < 1:
        raise ValueError(f"MACD signal({signal}) 必须 >= 1")


def _validate_boll_params(params: dict):
    w = params.get("window", 20)
    k = params.get("num_std", 2.0)
    if w < 2:
        raise ValueError(f"BOLL window({w}) 必须 >= 2")
    if k <= 0:
        raise ValueError(f"BOLL num_std({k}) 必须 > 0")


# ─── 指标注册表 ──────────────────────────────────────────────────────────────

INDICATOR_REGISTRY: dict[str, IndicatorSpec] = {
    "MA": IndicatorSpec(
        name="MA",
        params=[("window", int)],
        sql_template=(
            "AVG(close_adj) OVER ("
            "PARTITION BY ticker ORDER BY date "
            "ROWS BETWEEN {window_minus_1} PRECEDING AND CURRENT ROW)"
        ),
        validator=_validate_positive_window,
    ),
    "EMA": IndicatorSpec(
        name="EMA",
        params=[("window", int)],
        # DuckDB 没有原生 EMA，用 SMA 近似（v1 简化处理）
        sql_template=(
            "AVG(close_adj) OVER ("
            "PARTITION BY ticker ORDER BY date "
            "ROWS BETWEEN {window_minus_1} PRECEDING AND CURRENT ROW)"
        ),
        validator=_validate_positive_window,
    ),
    "RSI": IndicatorSpec(
        name="RSI",
        params=[("window", int)],
        sql_template=(
            "CASE WHEN AVG(CASE WHEN close_adj > LAG(close_adj) OVER (PARTITION BY ticker ORDER BY date) "
            "THEN close_adj - LAG(close_adj) OVER (PARTITION BY ticker ORDER BY date) ELSE 0 END) "
            "OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN {window_minus_1} PRECEDING AND CURRENT ROW) "
            "+ AVG(CASE WHEN close_adj < LAG(close_adj) OVER (PARTITION BY ticker ORDER BY date) "
            "THEN LAG(close_adj) OVER (PARTITION BY ticker ORDER BY date) - close_adj ELSE 0 END) "
            "OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN {window_minus_1} PRECEDING AND CURRENT ROW) = 0 "
            "THEN 50.0 "
            "ELSE 100.0 - 100.0 / (1.0 + "
            "AVG(CASE WHEN close_adj > LAG(close_adj) OVER (PARTITION BY ticker ORDER BY date) "
            "THEN close_adj - LAG(close_adj) OVER (PARTITION BY ticker ORDER BY date) ELSE 0 END) "
            "OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN {window_minus_1} PRECEDING AND CURRENT ROW) / "
            "AVG(CASE WHEN close_adj < LAG(close_adj) OVER (PARTITION BY ticker ORDER BY date) "
            "THEN LAG(close_adj) OVER (PARTITION BY ticker ORDER BY date) - close_adj ELSE 0 END) "
            "OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN {window_minus_1} PRECEDING AND CURRENT ROW)) "
            "END"
        ),
        validator=_validate_positive_window,
    ),
    "VOLUME": IndicatorSpec(
        name="VOLUME",
        params=[],
        sql_template="volume",
    ),
    "AMOUNT": IndicatorSpec(
        name="AMOUNT",
        params=[],
        sql_template="amount",
    ),
    "CLOSE": IndicatorSpec(
        name="CLOSE",
        params=[],
        sql_template="close_adj",
    ),
    "OPEN": IndicatorSpec(
        name="OPEN",
        params=[],
        sql_template="open",
    ),
    "HIGH": IndicatorSpec(
        name="HIGH",
        params=[],
        sql_template="high",
    ),
    "LOW": IndicatorSpec(
        name="LOW",
        params=[],
        sql_template="low",
    ),
}

# MACD 需要多个 CTE，单独处理
MACD_SPEC = IndicatorSpec(
    name="MACD",
    params=[("fast", int), ("slow", int), ("signal", int)],
    validator=_validate_macd_params,
)

# BOLL 需要多个 CTE，单独处理
BOLL_SPEC = IndicatorSpec(
    name="BOLL",
    params=[("window", int), ("num_std", float)],
    validator=_validate_boll_params,
)

# KDJ 需要多个 CTE，单独处理
KDJ_SPEC = IndicatorSpec(
    name="KDJ",
    params=[("window", int)],
    validator=_validate_positive_window,
)
