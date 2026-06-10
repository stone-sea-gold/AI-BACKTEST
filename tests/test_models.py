"""策略模型单元测试。"""

import pytest
from pydantic import ValidationError

from aiquant.strategy.conditions import ComparatorType, CombineType, IndicatorType
from aiquant.strategy.models import (
    BuyCondition,
    ConditionNode,
    PositionSizing,
    SellCondition,
    StopLoss,
    StockPool,
    StrategyConfig,
)


class TestConditionNode:
    def test_leaf_node(self):
        node = ConditionNode(indicator=IndicatorType.MA, comparator=ComparatorType.GT, value=10, params={"window": 5})
        assert node.indicator == IndicatorType.MA
        assert node.depth() == 1

    def test_branch_node(self):
        node = ConditionNode(
            operator=CombineType.AND,
            conditions=[
                ConditionNode(indicator=IndicatorType.MA, comparator=ComparatorType.GT, value=10, params={"window": 5}),
                ConditionNode(indicator=IndicatorType.VOLUME, comparator=ComparatorType.GT, value=1000000),
            ],
        )
        assert node.operator == CombineType.AND
        assert node.depth() == 2

    def test_leaf_without_comparator_raises(self):
        with pytest.raises(ValidationError):
            ConditionNode(indicator=IndicatorType.MA)

    def test_branch_with_indicator_raises(self):
        with pytest.raises(ValidationError):
            ConditionNode(operator=CombineType.AND, indicator=IndicatorType.MA)

    def test_neither_branch_nor_leaf_raises(self):
        with pytest.raises(ValidationError):
            ConditionNode()

    def test_depth_limit(self):
        deep = ConditionNode(indicator=IndicatorType.CLOSE, comparator=ComparatorType.GT, value=10)
        # depth 1-5 should be fine
        for _ in range(4):
            deep = ConditionNode(operator=CombineType.AND, conditions=[deep])
        assert deep.depth() == 5
        # depth 6 should raise
        with pytest.raises(ValidationError, match="深度"):
            ConditionNode(operator=CombineType.AND, conditions=[deep])


class TestStopLoss:
    def test_default(self):
        sl = StopLoss()
        assert sl.type == "none"
        assert sl.pct == 0.05


class TestPositionSizing:
    def test_default(self):
        ps = PositionSizing()
        assert ps.type == "fixed_pct"
        assert ps.pct == 0.1


class TestStrategyConfig:
    def test_custom_pool(self):
        config = StrategyConfig(
            stock_pool=StockPool.CUSTOM,
            custom_tickers=["000001", "600000"],
            buy_condition=BuyCondition(condition=ConditionNode(indicator=IndicatorType.CLOSE, comparator=ComparatorType.GT, value=10)),
            sell_condition=SellCondition(condition=ConditionNode(indicator=IndicatorType.CLOSE, comparator=ComparatorType.LT, value=5)),
        )
        assert config.custom_tickers == ["000001", "600000"]
        assert config.initial_cash == 1_000_000
