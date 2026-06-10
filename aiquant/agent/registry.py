"""Tool Registry 抽象（第一期：桩实现，第二期接入）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    success: bool
    data: dict | None = None
    error: str | None = None


class Tool(ABC):
    """Tool 抽象。"""

    name: str = ""
    description: str = ""

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        ...


class ToolRegistry:
    """Tool 注册中心。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [{"name": t.name, "description": t.description} for t in self._tools.values()]


class BacktestTool(Tool):
    """回测 Tool（桩实现）。"""

    name = "backtest"
    description = "执行策略回测"

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=False, error="回测 Tool 暂未实现")


class ScreenTool(Tool):
    """选股 Tool（桩实现）。"""

    name = "screen"
    description = "条件选股"

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=False, error="选股 Tool 暂未实现")
