"""异常驱动路由 — LLM → Pydantic 校验 → 回测执行。"""

from __future__ import annotations

import json
import uuid

from pydantic import ValidationError

from aiquant.agent.hub import LLMHub
from aiquant.agent.registry import BacktestTool, get_tool_definitions
from aiquant.agent.schemas import ChatResponse
from aiquant.agent.session import (
    ChatSession,
    build_error_message,
    build_escalation_message,
    compress_messages,
    extract_error_signature,
)
from aiquant.agent.prompts.strategy_prompt import build_system_prompt
from aiquant.config.logger import logger
from aiquant.store.sqlite_store import SQLiteStore


class Router:
    """异常驱动路由：LLM 生成 → Pydantic 校验 → 失败追问 → 循环。"""

    def __init__(self, hub: LLMHub, store: SQLiteStore | None = None,
                 max_loops: int = 3, max_messages: int = 20):
        self.hub = hub
        self.store = store or SQLiteStore()
        self.backtest_tool = BacktestTool()
        self.max_loops = max_loops
        self.max_messages = max_messages

    def _get_or_create_session(self, session_id: str | None) -> ChatSession:
        if session_id:
            data = self.store.get_session(session_id)
            if data:
                return ChatSession(
                    session_id=data["session_id"],
                    messages=data["messages"],
                    current_strategy=data.get("current_strategy"),
                    status=data["status"],
                    loop_count=data["loop_count"],
                    error_signature=data.get("error_signature"),
                    created_at=data["created_at"],
                    updated_at=data["updated_at"],
                )

        new_id = session_id or uuid.uuid4().hex[:12]
        self.store.create_session(new_id)
        return ChatSession(session_id=new_id, created_at="", updated_at="")

    def _save_session(self, session: ChatSession):
        self.store.update_session(
            session.session_id,
            messages=session.messages,
            status=session.status,
            loop_count=session.loop_count,
            error_signature=session.error_signature,
            current_strategy=session.current_strategy,
        )

    def _extract_strategy_from_tool_calls(self, tool_calls: list[dict]) -> dict:
        for tc in tool_calls:
            fn = tc.get("function", {})
            if fn.get("name") == "run_backtest":
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    return json.loads(args)
                return args
        return {}

    async def process_message(self, user_message: str,
                              session_id: str | None = None) -> ChatResponse:
        """处理用户消息的主循环。"""
        session = self._get_or_create_session(session_id)
        session.messages.append({"role": "user", "content": user_message})

        # 滑动窗口压缩
        if len(session.messages) > self.max_messages:
            session.messages, archived = compress_messages(session.messages, self.max_messages)
            if archived:
                self.store.archive_messages(session.session_id, archived)

        system_prompt = build_system_prompt()
        tools = get_tool_definitions()

        while session.loop_count < self.max_loops:
            messages_with_system = [
                {"role": "system", "content": system_prompt}
            ] + session.messages

            try:
                response = await self.hub.generate(messages_with_system, tools)
            except Exception as e:
                logger.error(f"LLM 调用失败: {e}")
                session.status = "aborted"
                self._save_session(session)
                return ChatResponse(
                    reply=f"LLM 服务异常: {e}",
                    session_id=session.session_id,
                    status="error",
                )

            if response.tool_calls:
                # LLM 输出了 Tool Call
                strategy_json = self._extract_strategy_from_tool_calls(response.tool_calls)
                session.messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": response.tool_calls,
                })

                # Pydantic 校验
                try:
                    config = _build_strategy_config(strategy_json)
                    session.status = "completed"
                    session.current_strategy = strategy_json
                    self._save_session(session)

                    # 执行回测
                    tool_result = await self.backtest_tool.execute(strategy_json)

                    if tool_result.success:
                        return ChatResponse(
                            reply=tool_result.data.get("report_text", "回测完成"),
                            session_id=session.session_id,
                            status="success",
                        )
                    else:
                        return ChatResponse(
                            reply=f"回测执行失败: {tool_result.error}",
                            session_id=session.session_id,
                            status="error",
                        )

                except ValidationError as e:
                    error_sig = extract_error_signature(e)
                    if error_sig == session.error_signature:
                        error_msg = build_escalation_message(e, session.loop_count)
                    else:
                        error_msg = build_error_message(e)

                    session.messages.append({"role": "system", "content": error_msg})
                    session.error_signature = error_sig
                    session.loop_count += 1
                    self._save_session(session)
                    continue

            elif response.content:
                # LLM 返回纯文本 → 拒绝/解释/追问
                session.messages.append({"role": "assistant", "content": response.content})

                # 判断是否是追问（follow_up）
                if session.loop_count < self.max_loops - 1:
                    session.loop_count += 1
                    self._save_session(session)
                    return ChatResponse(
                        reply=response.content,
                        session_id=session.session_id,
                        status="follow_up",
                    )
                else:
                    session.status = "aborted"
                    self._save_session(session)
                    return ChatResponse(
                        reply=response.content,
                        session_id=session.session_id,
                        status="error",
                    )

        # 超过 max_loops
        session.status = "aborted"
        self._save_session(session)
        return ChatResponse(
            reply="抱歉，无法将您的策略转化为标准配置。请简化表达后重试，或使用 JSON 格式直接配置。",
            session_id=session.session_id,
            status="error",
        )


def _build_strategy_config(data: dict):
    """从 dict 构建 StrategyConfig，做必要的字段补全。"""
    from aiquant.strategy.models import BuyCondition, SellCondition, ConditionNode

    # 如果 buy_condition/sell_condition 是裸条件树，包装一下
    if "buy_condition" in data and isinstance(data["buy_condition"], dict):
        bc = data["buy_condition"]
        if "condition" not in bc and ("indicator" in bc or "operator" in bc):
            data["buy_condition"] = {"condition": bc}

    if "sell_condition" in data and isinstance(data["sell_condition"], dict):
        sc = data["sell_condition"]
        if "condition" not in sc and ("indicator" in sc or "operator" in sc):
            data["sell_condition"] = {"condition": sc}

    from aiquant.strategy.models import StrategyConfig
    return StrategyConfig(**data)
