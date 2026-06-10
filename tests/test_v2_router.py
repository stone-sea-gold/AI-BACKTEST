"""v2 测试：异常驱动路由（mock LLM + BacktestTool）。"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from aiquant.agent.hub import LLMHub
from aiquant.agent.registry import ToolResult
from aiquant.agent.router import Router
from aiquant.providers.base import LLMResponse
from aiquant.store.sqlite_store import SQLiteStore


def _tmp_store() -> SQLiteStore:
    return SQLiteStore(Path(tempfile.mkdtemp()) / "test.db")


MOCK_REPORT_TEXT = (
    "绩效报告\n总收益率: 10.00%\n年化收益率: 5.00%\n"
    "最大回撤: 3.00%\n夏普比率: 1.20\n胜率: 60.00%\n"
    "总交易次数: 10\n期末净值: 1100000.00"
)


def _mock_backtest_result(*args, **kwargs):
    return ToolResult(
        success=True,
        data={"report_text": MOCK_REPORT_TEXT, "total_return": 0.1},
    )


VALID_STRATEGY = {
    "name": "test",
    "buy_condition": {
        "condition": {
            "indicator": "MA",
            "comparator": ">",
            "value": "ma20",
            "params": {"window": 5},
        }
    },
    "sell_condition": {
        "condition": {
            "indicator": "MA",
            "comparator": "<",
            "value": "ma20",
            "params": {"window": 20},
        }
    },
}


@pytest.mark.asyncio
async def test_router_success():
    """LLM 返回有效 Tool Call → 一轮成功。"""
    store = _tmp_store()
    hub = LLMHub()

    mock_response = LLMResponse(
        tool_calls=[{
            "id": "tc1",
            "function": {
                "name": "run_backtest",
                "arguments": json.dumps(VALID_STRATEGY, ensure_ascii=False),
            },
        }],
    )

    with patch.object(hub, "generate", new_callable=AsyncMock, return_value=mock_response), \
         patch("aiquant.agent.router.BacktestTool.execute", new_callable=AsyncMock, return_value=_mock_backtest_result()):
        router = Router(hub=hub, store=store)
        result = await router.process_message("帮我测均线金叉")

    assert result.status == "success"
    assert result.session_id


@pytest.mark.asyncio
async def test_router_follow_up():
    """LLM 返回纯文本 → follow_up。"""
    store = _tmp_store()
    hub = LLMHub()

    mock_response = LLMResponse(content="请问您想用哪个周期的均线？")

    with patch.object(hub, "generate", new_callable=AsyncMock, return_value=mock_response):
        router = Router(hub=hub, store=store)
        result = await router.process_message("帮我测均线")

    assert result.status == "follow_up"
    assert "均线" in result.reply


@pytest.mark.asyncio
async def test_router_validation_error_retry():
    """LLM 返回无效 JSON → 追问 → 第二次成功。"""
    store = _tmp_store()
    hub = LLMHub()

    invalid_response = LLMResponse(
        tool_calls=[{
            "id": "tc1",
            "function": {
                "name": "run_backtest",
                "arguments": json.dumps({"name": "bad", "buy_condition": {"condition": {"indicator": "MA"}}}),
            },
        }],
    )

    valid_response = LLMResponse(
        tool_calls=[{
            "id": "tc2",
            "function": {
                "name": "run_backtest",
                "arguments": json.dumps(VALID_STRATEGY, ensure_ascii=False),
            },
        }],
    )

    call_count = 0

    async def mock_generate(messages, tools=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return invalid_response
        return valid_response

    with patch.object(hub, "generate", side_effect=mock_generate), \
         patch("aiquant.agent.router.BacktestTool.execute", new_callable=AsyncMock, return_value=_mock_backtest_result()):
        router = Router(hub=hub, store=store)
        result = await router.process_message("帮我测均线金叉")

    assert result.status == "success"
    assert call_count == 2


@pytest.mark.asyncio
async def test_router_max_loops():
    """连续失败超过 max_loops → error。"""
    store = _tmp_store()
    hub = LLMHub()

    invalid_response = LLMResponse(
        tool_calls=[{
            "id": "tc1",
            "function": {
                "name": "run_backtest",
                "arguments": json.dumps({"name": "bad"}),
            },
        }],
    )

    with patch.object(hub, "generate", new_callable=AsyncMock, return_value=invalid_response):
        router = Router(hub=hub, store=store, max_loops=2)
        result = await router.process_message("帮我测均线金叉")

    assert result.status == "error"
    assert "无法" in result.reply
