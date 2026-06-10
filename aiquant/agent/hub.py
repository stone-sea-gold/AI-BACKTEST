"""LLM Hub 抽象（第一期：桩实现，第二期接入）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Literal


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict] | None = None


class LLMProvider(ABC):
    """LLM Provider 抽象。"""

    @abstractmethod
    async def generate(self, messages: list[dict], tools: list | None = None) -> LLMResponse:
        ...

    @abstractmethod
    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        ...


class LLMHub:
    """多 LLM Provider 路由。"""

    def __init__(self, routing_strategy: Literal["primary_only", "fallback", "ensemble"] = "primary_only"):
        self.providers: dict[str, LLMProvider] = {}
        self.routing_strategy = routing_strategy

    def register(self, name: str, provider: LLMProvider):
        self.providers[name] = provider

    async def route(self, messages: list[dict], tools: list | None = None) -> LLMResponse:
        if not self.providers:
            raise RuntimeError("未注册任何 LLM Provider")

        if self.routing_strategy == "primary_only":
            provider = next(iter(self.providers.values()))
            return await provider.generate(messages, tools)

        if self.routing_strategy == "fallback":
            last_error = None
            for provider in self.providers.values():
                try:
                    return await provider.generate(messages, tools)
                except Exception as e:
                    last_error = e
            raise RuntimeError(f"所有 Provider 均失败: {last_error}")

        raise NotImplementedError(f"路由策略 {self.routing_strategy} 暂未实现")
