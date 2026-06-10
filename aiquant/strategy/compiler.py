"""条件树 → DuckDB 窗口函数 SQL 编译器。

核心设计：
- 每个唯一的 (指标, 参数) 对生成一个独立 CTE
- CTE 别名包含参数，如 ind_ma_5, ind_macd_12_26_9
- 条件树中引用的指标表达式替换为 CTE 别名
- MACD/BOLL/KDJ 生成多层 CTE 链
"""

from __future__ import annotations

import re

from aiquant.config.logger import logger
from aiquant.engine.indicators import INDICATOR_REGISTRY
from aiquant.strategy.conditions import ComparatorType, CombineType, IndicatorType
from aiquant.strategy.models import ConditionNode, StrategyConfig


def _format_sql(sql: str) -> str:
    return " ".join(sql.split())


def _params_key(params: dict) -> str:
    """参数字典转为唯一后缀，如 {'window': 5} → '5', {'fast':12,'slow':26,'signal':9} → '12_26_9'。"""
    if not params:
        return ""
    return "_".join(str(v) for v in params.values())


def _make_alias(indicator: str, params: dict) -> str:
    """生成 CTE 别名，如 ind_ma_5, ind_rsi_14, ind_macd_12_26_9。"""
    key = _params_key(params)
    return f"ind_{indicator.lower()}_{key}" if key else f"ind_{indicator.lower()}"


# ─── 指标 SQL 片段生成 ──────────────────────────────────────────────────────

def _sql_ma(params: dict) -> str:
    w = params.get("window", 20)
    return (
        f"AVG(close_adj) OVER ("
        f"PARTITION BY ticker ORDER BY date "
        f"ROWS BETWEEN {w - 1} PRECEDING AND CURRENT ROW)"
    )


def _sql_ema(params: dict) -> str:
    # DuckDB 没有原生 EMA，v1 用 SMA 近似
    return _sql_ma(params)


def _sql_rsi(params: dict) -> str:
    w = params.get("window", 14)
    lag = "LAG(close_adj) OVER (PARTITION BY ticker ORDER BY date)"
    gain = (
        f"AVG(CASE WHEN close_adj > {lag} THEN close_adj - {lag} ELSE 0 END) "
        f"OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN {w - 1} PRECEDING AND CURRENT ROW)"
    )
    loss = (
        f"AVG(CASE WHEN close_adj < {lag} THEN {lag} - close_adj ELSE 0 END) "
        f"OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN {w - 1} PRECEDING AND CURRENT ROW)"
    )
    return (
        f"CASE WHEN {gain} + {loss} = 0 THEN 50.0 "
        f"ELSE 100.0 - 100.0 / (1.0 + {gain} / {loss}) END"
    )


def _sql_macd(params: dict) -> tuple[list[tuple[str, str]], str]:
    """MACD 返回 (辅助CTE列表, 最终列表达式)。

    MACD = EMA(fast) - EMA(slow)
    Signal = EMA(MACD, signal_period)
    Histogram = MACD - Signal

    返回的 CTE 列表：[(alias, sql_fragment), ...]
    最终列表达式引用这些 alias。
    """
    fast = params.get("fast", 12)
    slow = params.get("slow", 26)
    sig = params.get("signal", 9)
    key = _params_key(params)
    alias_prefix = f"ind_macd_{key}"

    # EMA 用 SMA 近似
    ema_fast = (
        f"AVG(close_adj) OVER ("
        f"PARTITION BY ticker ORDER BY date "
        f"ROWS BETWEEN {fast - 1} PRECEDING AND CURRENT ROW)"
    )
    ema_slow = (
        f"AVG(close_adj) OVER ("
        f"PARTITION BY ticker ORDER BY date "
        f"ROWS BETWEEN {slow - 1} PRECEDING AND CURRENT ROW)"
    )
    macd_line = f"({ema_fast}) - ({ema_slow})"

    # Signal line: SMA of MACD line
    # 需要先计算 macd_line，再对其求 SMA，所以用嵌套 CTE
    cte_ema_fast = (f"{alias_prefix}_ema_fast", ema_fast)
    cte_ema_slow = (f"{alias_prefix}_ema_slow", ema_slow)
    cte_macd = (f"{alias_prefix}_line", f"{ema_fast} - {ema_slow}")
    cte_signal = (
        f"{alias_prefix}_signal",
        f"AVG({ema_fast} - {ema_slow}) OVER ("
        f"PARTITION BY ticker ORDER BY date "
        f"ROWS BETWEEN {sig - 1} PRECEDING AND CURRENT ROW)"
    )
    cte_hist = (
        f"{alias_prefix}_hist",
        f"({ema_fast} - {ema_slow}) - "
        f"(AVG({ema_fast} - {ema_slow}) OVER ("
        f"PARTITION BY ticker ORDER BY date "
        f"ROWS BETWEEN {sig - 1} PRECEDING AND CURRENT ROW))"
    )

    # 用户可以引用 MACD (histogram), MACD_LINE, MACD_SIGNAL
    aux_ctes = [cte_ema_fast, cte_ema_slow, cte_macd, cte_signal, cte_hist]
    final_expr = cte_hist[0]  # 默认 MACD = histogram
    return aux_ctes, final_expr


def _sql_boll(params: dict) -> tuple[list[tuple[str, str]], str]:
    """BOLL 返回 (辅助CTE列表, 最终列表达式)。

    中轨 = MA(window)
    上轨 = 中轨 + num_std * STDDEV(window)
    下轨 = 中轨 - num_std * STDDEV(window)

    返回 BOLL_MID 作为默认引用，用户可引用 BOLL_UPPER, BOLL_LOWER。
    """
    w = params.get("window", 20)
    k = params.get("num_std", 2.0)
    key = _params_key(params)
    alias_prefix = f"ind_boll_{key}"

    mid = (
        f"AVG(close_adj) OVER ("
        f"PARTITION BY ticker ORDER BY date "
        f"ROWS BETWEEN {w - 1} PRECEDING AND CURRENT ROW)"
    )
    std = (
        f"STDDEV_SAMP(close_adj) OVER ("
        f"PARTITION BY ticker ORDER BY date "
        f"ROWS BETWEEN {w - 1} PRECEDING AND CURRENT ROW)"
    )
    upper = f"({mid}) + {k} * ({std})"
    lower = f"({mid}) - {k} * ({std})"

    cte_mid = (f"{alias_prefix}_mid", mid)
    cte_std = (f"{alias_prefix}_std", std)
    cte_upper = (f"{alias_prefix}_upper", upper)
    cte_lower = (f"{alias_prefix}_lower", lower)

    aux_ctes = [cte_mid, cte_std, cte_upper, cte_lower]
    return aux_ctes, cte_mid[0]


def _sql_kdj(params: dict) -> tuple[list[tuple[str, str]], str]:
    """KDJ 返回 (辅助CTE列表, 最终列表达式)。

    RSV = (close - LOW_N) / (HIGH_N - LOW_N) * 100
    K = SMA(RSV, 3)  (用 AVG 近似)
    D = SMA(K, 3)
    J = 3K - 2D

    返回 K 作为默认引用，用户可引用 KDJ_K, KDJ_D, KDJ_J。
    """
    w = params.get("window", 9)
    key = _params_key(params)
    alias_prefix = f"ind_kdj_{key}"

    high_n = (
        f"MAX(high) OVER ("
        f"PARTITION BY ticker ORDER BY date "
        f"ROWS BETWEEN {w - 1} PRECEDING AND CURRENT ROW)"
    )
    low_n = (
        f"MIN(low) OVER ("
        f"PARTITION BY ticker ORDER BY date "
        f"ROWS BETWEEN {w - 1} PRECEDING AND CURRENT ROW)"
    )
    rsv = (
        f"CASE WHEN {high_n} = {low_n} THEN 50.0 "
        f"ELSE (close - {low_n}) / ({high_n} - {low_n}) * 100 END"
    )
    k = (
        f"AVG({rsv}) OVER ("
        f"PARTITION BY ticker ORDER BY date "
        f"ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)"
    )
    d = (
        f"AVG({k}) OVER ("
        f"PARTITION BY ticker ORDER BY date "
        f"ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)"
    )
    j = f"3 * ({k}) - 2 * ({d})"

    cte_rsv = (f"{alias_prefix}_rsv", rsv)
    cte_k = (f"{alias_prefix}_k", k)
    cte_d = (f"{alias_prefix}_d", d)
    cte_j = (f"{alias_prefix}_j", j)

    aux_ctes = [cte_rsv, cte_k, cte_d, cte_j]
    return aux_ctes, cte_k[0]


# ─── 简单指标映射 ──────────────────────────────────────────────────────────

_SIMPLE_INDICATORS = {
    "MA": _sql_ma,
    "EMA": _sql_ema,
    "RSI": _sql_rsi,
    "VOLUME": lambda p: "volume",
    "AMOUNT": lambda p: "amount",
    "CLOSE": lambda p: "close_adj",
    "OPEN": lambda p: "open",
    "HIGH": lambda p: "high",
    "LOW": lambda p: "low",
    "TURNOVER": lambda p: "turnover_ratio",
}

_COMPLEX_INDICATORS = {
    "MACD": _sql_macd,
    "BOLL": _sql_boll,
    "KDJ": _sql_kdj,
}


# ─── 条件树遍历 ──────────────────────────────────────────────────────────────

_INDICATOR_ALIASES = {
    "ma": "MA", "ema": "EMA", "rsi": "RSI", "macd": "MACD",
    "boll": "BOLL", "kdj": "KDJ", "close": "CLOSE", "open": "OPEN",
    "high": "HIGH", "low": "LOW", "volume": "VOLUME", "amount": "AMOUNT",
    "turnover": "TURNOVER",
}


def _parse_value_indicator(val) -> tuple[str, dict] | None:
    """解析 value 中的指标引用，如 "ma20" → ("MA", {"window": 20}), "boll_upper_20" → None。"""
    if not isinstance(val, str):
        return None
    m = re.match(r"^(ma|ema|rsi|macd|boll|kdj|close|open|high|low|volume|amount|turnover)(\d+)$", val, re.IGNORECASE)
    if m:
        ind_name = _INDICATOR_ALIASES[m.group(1).lower()]
        param_val = int(m.group(2))
        # 根据指标类型确定参数名
        if ind_name in ("MA", "EMA", "RSI"):
            return (ind_name, {"window": param_val})
        elif ind_name == "MACD":
            return (ind_name, {"fast": param_val, "slow": 26, "signal": 9})
        elif ind_name == "BOLL":
            return (ind_name, {"window": param_val, "num_std": 2.0})
        elif ind_name == "KDJ":
            return (ind_name, {"window": param_val})
    return None


def _collect_indicator_specs(node: ConditionNode) -> set[tuple[str, tuple]]:
    """收集条件树中所有唯一的 (指标名, 参数元组) 对。"""
    specs = set()
    if node.indicator is not None:
        params_tuple = tuple(sorted(node.params.items())) if node.params else ()
        specs.add((node.indicator.value, params_tuple))
        # 检查 value 是否引用了另一个指标
        ref = _parse_value_indicator(node.value)
        if ref:
            specs.add((ref[0], tuple(sorted(ref[1].items()))))
    for child in node.conditions:
        specs.update(_collect_indicator_specs(child))
    return specs


def _build_cte_chain(specs: set[tuple[str, tuple]]) -> tuple[str, dict[tuple, str]]:
    """为每个唯一的 (指标, 参数) 生成 CTE，返回 (cte_sql, {spec: final_expr})。"""
    cte_parts: list[tuple[str, str]] = []  # [(alias, sql_expr), ...]
    spec_to_expr: dict[tuple, str] = {}

    for ind_name, params_tuple in sorted(specs):
        params = dict(params_tuple)

        # 原始列直接引用，不需要 CTE
        if ind_name in _SIMPLE_INDICATORS and ind_name in ("VOLUME", "AMOUNT", "CLOSE", "OPEN", "HIGH", "LOW"):
            alias = _make_alias(ind_name, params)
            expr = _SIMPLE_INDICATORS[ind_name](params)
            spec_to_expr[(ind_name, params_tuple)] = expr
            continue

        # 简单指标：单个 CTE
        if ind_name in _SIMPLE_INDICATORS:
            alias = _make_alias(ind_name, params)
            expr = _SIMPLE_INDICATORS[ind_name](params)
            cte_parts.append((alias, expr))
            spec_to_expr[(ind_name, params_tuple)] = alias
            continue

        # 复杂指标：多层 CTE
        if ind_name in _COMPLEX_INDICATORS:
            aux_ctes, final_expr = _COMPLEX_INDICATORS[ind_name](params)
            cte_parts.extend(aux_ctes)
            spec_to_expr[(ind_name, params_tuple)] = final_expr
            continue

        # 指标注册表回退
        spec = INDICATOR_REGISTRY.get(ind_name)
        if spec and spec.sql_template:
            alias = _make_alias(ind_name, params)
            template_params = dict(params)
            if "window" in template_params:
                template_params["window_minus_1"] = template_params["window"] - 1
            expr = spec.sql_template.format(**template_params)
            cte_parts.append((alias, expr))
            spec_to_expr[(ind_name, params_tuple)] = alias
            continue

        logger.warning(f"指标 {ind_name} 无 SQL 模板，跳过")

    if not cte_parts:
        return "indicators AS (SELECT * FROM base)", spec_to_expr

    select_parts = ", ".join(f"{expr} AS {alias}" for alias, expr in cte_parts)
    return f"indicators AS ( SELECT *, {select_parts} FROM base )", spec_to_expr


# ─── 条件编译 ──────────────────────────────────────────────────────────────

def compile_indicator_expr(indicator: IndicatorType, params: dict, spec_to_expr: dict) -> str:
    """根据指标和参数，返回对应的 CTE 别名或内联表达式。"""
    params_tuple = tuple(sorted(params.items())) if params else ()
    key = (indicator.value, params_tuple)
    if key in spec_to_expr:
        return spec_to_expr[key]
    # 回退：直接编译
    if indicator.value in _SIMPLE_INDICATORS:
        return _SIMPLE_INDICATORS[indicator.value](params)
    raise NotImplementedError(f"指标 {indicator.value} 未在 CTE 链中生成")


def _compile_leaf(node: ConditionNode, spec_to_expr: dict) -> str:
    """编译叶子节点为 SQL 条件。"""
    indicator_sql = compile_indicator_expr(node.indicator, node.params, spec_to_expr)
    comp = node.comparator
    val = node.value

    # 解析 value 中的指标引用（如 "ma20" → CTE 别名）
    val_sql = _resolve_value(val, spec_to_expr)

    if comp == ComparatorType.GT:
        return f"({indicator_sql}) > {val_sql}"
    elif comp == ComparatorType.LT:
        return f"({indicator_sql}) < {val_sql}"
    elif comp == ComparatorType.GTE:
        return f"({indicator_sql}) >= {val_sql}"
    elif comp == ComparatorType.LTE:
        return f"({indicator_sql}) <= {val_sql}"
    elif comp == ComparatorType.EQ:
        return f"({indicator_sql}) = {val_sql}"
    elif comp == ComparatorType.CROSS_ABOVE:
        return (
            f"({indicator_sql}) > {val_sql} "
            f"AND LAG({indicator_sql}) OVER (PARTITION BY ticker ORDER BY date) "
            f"<= LAG({val_sql}) OVER (PARTITION BY ticker ORDER BY date)"
        )
    elif comp == ComparatorType.CROSS_BELOW:
        return (
            f"({indicator_sql}) < {val_sql} "
            f"AND LAG({indicator_sql}) OVER (PARTITION BY ticker ORDER BY date) "
            f">= LAG({val_sql}) OVER (PARTITION BY ticker ORDER BY date)"
        )
    elif comp == ComparatorType.BETWEEN:
        if not isinstance(val, (list, tuple)) or len(val) != 2:
            raise ValueError("between 需要 [low, high] 两个值")
        return f"({indicator_sql}) BETWEEN {val[0]} AND {val[1]}"
    else:
        raise ValueError(f"未知比较运算符: {comp}")


def _resolve_value(val, spec_to_expr: dict) -> str:
    """解析 value — 数字直接返回，指标引用解析为 CTE 表达式。"""
    if isinstance(val, (int, float)):
        return str(val)
    if not isinstance(val, str):
        return str(val)

    ref = _parse_value_indicator(val)
    if ref:
        ind_name, params = ref
        params_tuple = tuple(sorted(params.items()))
        key = (ind_name, params_tuple)
        if key in spec_to_expr:
            return spec_to_expr[key]
        # 回退：直接生成表达式
        if ind_name in _SIMPLE_INDICATORS:
            return _SIMPLE_INDICATORS[ind_name](params)
        raise ValueError(f"value 引用了指标 {val}，但未找到对应的 CTE")

    # 不是指标引用，当作字面值（数字字符串等）
    return val


def compile_conditions(node: ConditionNode, spec_to_expr: dict) -> str:
    """递归编译条件树为 SQL 表达式。"""
    if node.indicator is not None:
        return _compile_leaf(node, spec_to_expr)

    op = node.operator
    children = node.conditions
    if not children:
        raise ValueError("分支节点必须有子条件")

    child_sqls = [compile_conditions(c, spec_to_expr) for c in children]

    if op == CombineType.AND:
        return "(" + " AND ".join(child_sqls) + ")"
    elif op == CombineType.OR:
        return "(" + " OR ".join(child_sqls) + ")"
    elif op == CombineType.NOT:
        if len(child_sqls) != 1:
            raise ValueError("NOT 只能有一个子条件")
        return f"(NOT {child_sqls[0]})"
    else:
        raise ValueError(f"未知逻辑运算符: {op}")


# ─── 主入口 ──────────────────────────────────────────────────────────────

def build_backtest_query(config: StrategyConfig, tickers: list[str]) -> str:
    """生成完整回测查询 SQL。"""
    if not tickers:
        raise ValueError("标的池为空")

    # 1. 收集所有唯一的 (指标, 参数) 对
    buy_specs = _collect_indicator_specs(config.buy_condition.condition)
    sell_specs = _collect_indicator_specs(config.sell_condition.condition)
    all_specs = buy_specs | sell_specs

    # 2. 生成指标 CTE 链
    indicators_cte, spec_to_expr = _build_cte_chain(all_specs)

    # 3. ticker IN 子句
    ticker_list = ", ".join(f"'{t}'" for t in tickers)

    # 4. 基础数据 CTE
    base_cte = (
        f"base AS ( "
        f"SELECT *, "
        f"close * adj_factor / MAX(adj_factor) OVER (PARTITION BY ticker) AS close_adj "
        f"FROM daily_kline "
        f"WHERE ticker IN ({ticker_list}) "
        f"AND date BETWEEN '{config.start_date}' AND '{config.end_date}' "
        f")"
    )

    # 5. 信号 CTE
    buy_sql = compile_conditions(config.buy_condition.condition, spec_to_expr)
    sell_sql = compile_conditions(config.sell_condition.condition, spec_to_expr)

    signals_cte = (
        f"signals AS ( "
        f"SELECT ticker, date, open, close, close_adj, "
        f"CASE WHEN {buy_sql} THEN 1 ELSE 0 END AS buy_signal, "
        f"CASE WHEN {sell_sql} THEN 1 ELSE 0 END AS sell_signal "
        f"FROM indicators "
        f")"
    )

    # 6. 最终查询
    final = (
        "SELECT ticker, date, open, close, close_adj, buy_signal, sell_signal "
        "FROM signals "
        "WHERE buy_signal = 1 OR sell_signal = 1 "
        "ORDER BY date, ticker"
    )

    return _format_sql(f"WITH {base_cte}, {indicators_cte}, {signals_cte} {final}")
