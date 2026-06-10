"""DeepSeek Provider (OpenAI 兼容)。"""

from __future__ import annotations

from openai import AsyncOpenAI

from aiquant.providers.base import BaseProvider, LLMConfig, LLMResponse


class DeepSeekProvider(BaseProvider):
    """DeepSeek Provider，使用 OpenAI 兼容协议。"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=self.base_url,
        )

    async def generate(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        kwargs = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = await self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]

        return LLMResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            raw=resp.model_dump() if hasattr(resp, "model_dump") else None,
        )
