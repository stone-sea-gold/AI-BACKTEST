"""Tool Registry — BacktestTool 实际实现 + 工具定义自动生成。"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from aiquant.engine.core import run_backtest
from aiquant.engine.performance import calculate_performance, format_report
from aiquant.store.duckdb_store import DuckDBStore
from aiquant.strategy.models import StrategyConfig


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


def get_tool_definitions() -> list[dict]:
    """生成 OpenAI function calling 格式的工具定义。"""
    schema = StrategyConfig.model_json_schema()
    # 移除 Pydantic 的 $defs 引用，内联到 parameters
    if "$defs" in schema:
        defs = schema.pop("$defs")
        schema = _inline_refs(schema, defs, set())

    return [{
        "type": "function",
        "function": {
            "name": "run_backtest",
            "description": "执行 A 股策略回测。传入完整的策略配置 JSON，返回回测绩效报告。",
            "parameters": schema,
        },
    }]


def _inline_refs(obj, defs: dict, visited: set[str]):
    """将 $ref 引用内联展开，处理自引用（如 ConditionNode 递归）。"""
    if isinstance(obj, dict):
        if "$ref" in obj:
            ref_name = obj["$ref"].split("/")[-1]
            if ref_name in visited:
                # 已访问过的自引用 → 用简化的 object 占位
                return {"type": "object", "description": f"(递归结构: {ref_name})"}
            resolved = defs.get(ref_name, {})
            visited.add(ref_name)
            result = _inline_refs(resolved, defs, visited)
            visited.discard(ref_name)
            return result
        return {k: _inline_refs(v, defs, visited) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_inline_refs(item, defs, visited) for item in obj]
    return obj


class BacktestTool(Tool):
    """回测 Tool — 实际执行。"""

    name = "run_backtest"
    description = "执行 A 股策略回测"

    def __init__(self, store: DuckDBStore | None = None):
        self._store = store

    @property
    def store(self) -> DuckDBStore:
        if self._store is None:
            self._store = DuckDBStore()
        return self._store

    async def execute(self, params: dict) -> ToolResult:
        try:
            config = StrategyConfig(**params)
            result = run_backtest(config, self.store)
            report = calculate_performance(result)
            return ToolResult(
                success=True,
                data={
                    "total_return": report.total_return,
                    "annual_return": report.annual_return,
                    "max_drawdown": report.max_drawdown,
                    "sharpe_ratio": report.sharpe_ratio,
                    "win_rate": report.win_rate,
                    "total_trades": report.total_trades,
                    "final_value": report.final_value,
                    "report_text": format_report(report),
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class ScreenTool(Tool):
    """选股 Tool（桩实现）。"""

    name = "screen"
    description = "条件选股"

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=False, error="选股 Tool 暂未实现")
