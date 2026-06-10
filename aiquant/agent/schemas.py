"""Chat 请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Chat 请求。"""
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    """Chat 响应。"""
    reply: str
    session_id: str
    status: Literal["follow_up", "success", "error", "abort"]


class LLMConfigRequest(BaseModel):
    """LLM 配置请求。"""
    provider: Literal["deepseek", "claude", "openai", "other"] = "deepseek"
    api_key: str
    base_url: str | None = None
    model: str = "deepseek-chat"
    max_tokens: int = 4096
    temperature: float = 0.1
