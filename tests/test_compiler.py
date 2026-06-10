"""编译器单元测试。"""

import pytest

from aiquant.strategy.compiler import (
    build_backtest_query,
    compile_conditions,
    _collect_indicator_specs,
    _make_alias,
)
from aiquant.strategy.conditions import ComparatorType, CombineType, IndicatorType
from aiquant.strategy.models import (
    BuyCondition,
    ConditionNode,
    SellCondition,
    StockPool,
    StrategyConfig,
)


def _simple_config(buy_node, sell_node, **kwargs):
    defaults = dict(
        name="test",
        stock_pool=StockPool.CUSTOM,
        custom_tickers=["000001"],
        start_date="2024-01-01",
        end_date="2024-12-31",
        buy_condition=BuyCondition(condition=buy_node),
        sell_condition=SellCondition(condition=sell_node),
    )
    defaults.update(kwargs)
    return StrategyConfig(**defaults)


class TestMakeAlias:
    def test_simple(self):
        assert _make_alias("MA", {"window": 5}) == "ind_ma_5"

    def test_multi_params(self):
        alias = _make_alias("MACD", {"fast": 12, "slow": 26, "signal": 9})
        assert alias.startswith("ind_macd_")

    def test_no_params(self):
        assert _make_alias("CLOSE", {}) == "ind_close"


class TestCollectIndicatorSpecs:
    def test_single_indicator(self):
        node = ConditionNode(indicator=IndicatorType.MA, comparator=ComparatorType.GT, value=10, params={"window": 5})
        specs = _collect_indicator_specs(node)
        assert ("MA", (("window", 5),)) in specs

    def test_multiple_indicators(self):
        node = ConditionNode(
            operator=CombineType.AND,
            conditions=[
                ConditionNode(indicator=IndicatorType.MA, comparator=ComparatorType.GT, value=10, params={"window": 5}),
                ConditionNode(indicator=IndicatorType.RSI, comparator=ComparatorType.LT, value=30, params={"window": 14}),
            ],
        )
        specs = _collect_indicator_specs(node)
        assert len(specs) == 2

    def test_same_indicator_different_params(self):
        node = ConditionNode(
            operator=CombineType.AND,
            conditions=[
                ConditionNode(indicator=IndicatorType.MA, comparator=ComparatorType.GT, value=10, params={"window": 5}),
                ConditionNode(indicator=IndicatorType.MA, comparator=ComparatorType.LT, value=20, params={"window": 20}),
            ],
        )
        specs = _collect_indicator_specs(node)
        assert len(specs) == 2
        assert ("MA", (("window", 5),)) in specs
        assert ("MA", (("window", 20),)) in specs


class TestCompileConditions:
    def test_simple_gt(self):
        from aiquant.strategy.compiler import _build_cte_chain
        specs = {("CLOSE", ())}
        _, spec_to_expr = _build_cte_chain(specs)
        node = ConditionNode(indicator=IndicatorType.CLOSE, comparator=ComparatorType.GT, value=10.0)
        sql = compile_conditions(node, spec_to_expr)
        assert "> 10.0" in sql

    def test_and_conditions(self):
        from aiquant.strategy.compiler import _build_cte_chain
        specs = {("MA", (("window", 5),)), ("VOLUME", ())}
        _, spec_to_expr = _build_cte_chain(specs)
        node = ConditionNode(
            operator=CombineType.AND,
            conditions=[
                ConditionNode(indicator=IndicatorType.MA, comparator=ComparatorType.GT, value=10, params={"window": 5}),
                ConditionNode(indicator=IndicatorType.VOLUME, comparator=ComparatorType.GT, value=1000000),
            ],
        )
        sql = compile_conditions(node, spec_to_expr)
        assert "AND" in sql
        assert "ind_ma_5" in sql


class TestBuildBacktestQuery:
    def test_ma_params_different(self):
        """MA(5) 和 MA(20) 必须生成不同的 CTE 别名。"""
        buy = ConditionNode(indicator=IndicatorType.MA, comparator=ComparatorType.GT, value=10, params={"window": 5})
        sell = ConditionNode(indicator=IndicatorType.MA, comparator=ComparatorType.LT, value=10, params={"window": 20})
        config = _simple_config(buy, sell)
        sql = build_backtest_query(config, ["000001"])
        assert "ind_ma_5" in sql
        assert "ind_ma_20" in sql

    def test_macd_in_sql(self):
        buy = ConditionNode(indicator=IndicatorType.MACD, comparator=ComparatorType.GT, value=0, params={"fast": 12, "slow": 26, "signal": 9})
        sell = ConditionNode(indicator=IndicatorType.MACD, comparator=ComparatorType.LT, value=0, params={"fast": 12, "slow": 26, "signal": 9})
        config = _simple_config(buy, sell)
        sql = build_backtest_query(config, ["000001"])
        assert "ind_macd_" in sql
        assert "ema_fast" in sql

    def test_boll_in_sql(self):
        buy = ConditionNode(indicator=IndicatorType.BOLL, comparator=ComparatorType.LT, value=0, params={"window": 20, "num_std": 2.0})
        sell = ConditionNode(indicator=IndicatorType.BOLL, comparator=ComparatorType.GT, value=100, params={"window": 20, "num_std": 2.0})
        config = _simple_config(buy, sell)
        sql = build_backtest_query(config, ["000001"])
        assert "ind_boll_" in sql
        assert "STDDEV" in sql

    def test_kdj_in_sql(self):
        buy = ConditionNode(indicator=IndicatorType.KDJ, comparator=ComparatorType.LT, value=20, params={"window": 9})
        sell = ConditionNode(indicator=IndicatorType.KDJ, comparator=ComparatorType.GT, value=80, params={"window": 9})
        config = _simple_config(buy, sell)
        sql = build_backtest_query(config, ["000001"])
        assert "ind_kdj_" in sql
        assert "RSV" in sql.upper() or "rsv" in sql

    def test_empty_tickers_raises(self):
        buy = ConditionNode(indicator=IndicatorType.CLOSE, comparator=ComparatorType.GT, value=10)
        sell = ConditionNode(indicator=IndicatorType.CLOSE, comparator=ComparatorType.LT, value=5)
        config = _simple_config(buy, sell)
        with pytest.raises(ValueError, match="标的池为空"):
            build_backtest_query(config, [])
