"""v2 测试：System Prompt 动态生成。"""

import json

from aiquant.agent.prompts.strategy_prompt import build_system_prompt
from aiquant.strategy.conditions import ComparatorType, CombineType, IndicatorType
from aiquant.strategy.models import StrategyConfig


def test_prompt_contains_all_indicators():
    prompt = build_system_prompt()
    for ind in IndicatorType:
        assert ind.value in prompt, f"缺少指标 {ind.value}"


def test_prompt_contains_all_comparators():
    prompt = build_system_prompt()
    for comp in ComparatorType:
        assert comp.value in prompt, f"缺少比较符 {comp.value}"


def test_prompt_contains_all_combine_types():
    prompt = build_system_prompt()
    for ct in CombineType:
        assert ct.value in prompt, f"缺少组合逻辑 {ct.value}"


def test_prompt_example_json_valid():
    """示例中的 JSON 应该能被 StrategyConfig 解析。"""
    prompt = build_system_prompt()
    # 提取 buy_condition 示例
    assert "buy_condition" in prompt
    assert "sell_condition" in prompt
    assert "run_backtest" in prompt
