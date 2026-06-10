"""Pydantic 策略/条件树模型。"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from aiquant.strategy.conditions import ComparatorType, CombineType, IndicatorType

MAX_CONDITION_DEPTH = 5


class ConditionNode(BaseModel):
    """递归条件树。叶子节点用 indicator/comparator/value，分支节点用 operator/conditions。"""

    # 分支节点字段
    operator: CombineType | None = None
    conditions: list[ConditionNode] = Field(default_factory=list)

    # 叶子节点字段
    indicator: IndicatorType | None = None
    comparator: ComparatorType | None = None
    value: float | str | None = None
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_node(self) -> "ConditionNode":
        is_branch = self.operator is not None
        is_leaf = self.indicator is not None
        if not is_branch and not is_leaf:
            raise ValueError("条件节点必须是分支节点(operator+conditions)或叶子节点(indicator+comparator+value)")
        if is_branch and is_leaf:
            raise ValueError("分支节点不应设置 indicator")
        if is_leaf and self.comparator is None:
            raise ValueError("叶子节点必须设置 comparator")
        return self

    def depth(self) -> int:
        if not self.conditions:
            return 1
        return 1 + max(c.depth() for c in self.conditions)

    @model_validator(mode="after")
    def check_depth(self) -> "ConditionNode":
        if self.depth() > MAX_CONDITION_DEPTH:
            raise ValueError(f"条件树深度超过限制 ({MAX_CONDITION_DEPTH})")
        return self


class StopLoss(BaseModel):
    """止损规则。"""
    type: Literal["none", "fixed", "trailing", "atr"] = "none"
    pct: float = 0.05           # 止损比例 (5%)
    atr_multiplier: float = 2.0 # ATR 止损倍数


class PositionSizing(BaseModel):
    """仓位管理。"""
    type: Literal["fixed_shares", "fixed_pct"] = "fixed_pct"
    shares: int = 100           # fixed_shares 模式：每次买多少股
    pct: float = 0.1            # fixed_pct 模式：每次用可用资金的百分比


class StockPool(str, Enum):
    """标的池类型。"""
    CSI300 = "csi300"
    CSI500 = "csi500"
    ALL_A = "all_a"
    CUSTOM = "custom"


class BuyCondition(BaseModel):
    """买入条件。"""
    condition: ConditionNode


class SellCondition(BaseModel):
    """卖出条件。"""
    condition: ConditionNode


class StrategyConfig(BaseModel):
    """完整策略配置。"""
    name: str = "unnamed"
    description: str = ""

    # 标的池
    stock_pool: StockPool = StockPool.CSI300
    custom_tickers: list[str] | None = None

    # 时间范围
    start_date: str = "2023-01-01"
    end_date: str = "2025-12-31"

    # 买卖条件
    buy_condition: BuyCondition
    sell_condition: SellCondition

    # 风控
    stop_loss: StopLoss = Field(default_factory=StopLoss)
    position_sizing: PositionSizing = Field(default_factory=PositionSizing)

    # 初始资金
    initial_cash: float = 1_000_000.0
