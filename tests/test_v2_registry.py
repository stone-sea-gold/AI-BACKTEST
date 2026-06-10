"""v2 测试：Tool Registry 与工具定义。"""

from aiquant.agent.registry import BacktestTool, get_tool_definitions


def test_tool_definitions_structure():
    tools = get_tool_definitions()
    assert len(tools) == 1
    tool = tools[0]
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "run_backtest"
    assert "parameters" in tool["function"]


def test_tool_definitions_parameters_has_required_fields():
    tools = get_tool_definitions()
    params = tools[0]["function"]["parameters"]
    # StrategyConfig 的必填字段
    assert "properties" in params
    props = params["properties"]
    assert "buy_condition" in props
    assert "sell_condition" in props


def test_backtest_tool_name():
    tool = BacktestTool()
    assert tool.name == "run_backtest"


def test_tool_definitions_no_dollar_ref():
    """确保 $ref 已被内联展开。"""
    import json
    tools = get_tool_definitions()
    text = json.dumps(tools)
    assert "$ref" not in text, "工具定义中不应有 $ref 引用"
