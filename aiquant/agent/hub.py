"""LLM Hub — 多 Provider 路由与 fallback。"""

from __future__ import annotations

from typing import Literal

from aiquant.providers.base import BaseProvider, LLMConfig, LLMResponse


def _create_provider(config: LLMConfig) -> BaseProvider:
    """根据配置创建对应 Provider。"""
    provider = config.provider
    if provider == "deepseek" or (provider == "other" and "deepseek" in (config.base_url or "")):
        from aiquant.providers.deepseek_provider import DeepSeekProvider
        return DeepSeekProvider(config)
    elif provider == "claude" or config.api_key.startswith("sk-ant-"):
        from aiquant.providers.claude_provider import ClaudeProvider
        return ClaudeProvider(config)
    elif provider == "openai":
        from aiquant.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(config)
    elif provider == "other":
        from aiquant.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(config)
    else:
        raise ValueError(f"不支持的 provider: {provider}")


class LLMHub:
    """多 LLM Provider 路由，支持 fallback。"""

    def __init__(self, configs: list[LLMConfig] | None = None,
                 strategy: Literal["primary_only", "fallback"] = "primary_only"):
        self.providers: list[BaseProvider] = []
        self.strategy = strategy
        if configs:
            for cfg in configs:
                self.add(cfg)

    def add(self, config: LLMConfig):
        provider = _create_provider(config)
        self.providers.append(provider)

    async def generate(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        if not self.providers:
            raise RuntimeError("未注册任何 LLM Provider，请先配置 LLM")

        if self.strategy == "primary_only":
            return await self.providers[0].generate(messages, tools)

        if self.strategy == "fallback":
            last_error: Exception | None = None
            for provider in self.providers:
                try:
                    return await provider.generate(messages, tools)
                except Exception as e:
                    last_error = e
            raise RuntimeError(f"所有 Provider 均失败: {last_error}")

        raise NotImplementedError(f"路由策略 {self.strategy} 暂未实现")
