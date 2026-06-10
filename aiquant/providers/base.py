"""LLM 配置与 Provider 基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal

from pydantic import BaseModel

# 厂商 → Base URL 映射
PROVIDER_URL_MAP: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "claude": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
}


class LLMConfig(BaseModel):
    """LLM 配置。"""
    provider: Literal["deepseek", "claude", "openai", "other"] = "deepseek"
    api_key: str
    base_url: str | None = None
    model: str = "deepseek-chat"
    max_tokens: int = 4096
    temperature: float = 0.1


@dataclass
class LLMResponse:
    """LLM 响应。"""
    content: str = ""
    tool_calls: list[dict] | None = None
    raw: dict | None = None


class BaseProvider(ABC):
    """Provider 基类。"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.base_url = config.base_url or PROVIDER_URL_MAP.get(config.provider, "")
        if not self.base_url:
            raise ValueError(f"provider={config.provider} 必须提供 base_url")

    @abstractmethod
    async def generate(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        ...

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        raise NotImplementedError("流式输出暂未实现")
        yield  # make it an async generator


def is_anthropic(config: LLMConfig) -> bool:
    """判断是否使用 Anthropic 协议。"""
    return config.provider == "claude" or config.api_key.startswith("sk-ant-")
