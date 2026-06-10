"""Claude Provider (Anthropic 协议)。"""

from __future__ import annotations

import anthropic

from aiquant.providers.base import BaseProvider, LLMConfig, LLMResponse


def _to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """OpenAI messages → Anthropic (system, messages) 格式。"""
    system_parts = []
    anthropic_msgs = []

    for msg in messages:
        role = msg["role"]
        if role == "system":
            system_parts.append(msg["content"])
        else:
            anthropic_msgs.append({"role": role, "content": msg["content"]})

    return "\n\n".join(system_parts), anthropic_msgs


def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
    """OpenAI tools → Anthropic tools 格式。"""
    result = []
    for t in tools:
        fn = t["function"]
        result.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn["parameters"],
        })
    return result


def _parse_tool_use(response) -> list[dict] | None:
    """从 Anthropic 响应中提取 tool_use 块。"""
    tool_calls = []
    for block in response.content:
        if block.type == "tool_use":
            import json
            tool_calls.append({
                "id": block.id,
                "function": {
                    "name": block.name,
                    "arguments": json.dumps(block.input, ensure_ascii=False),
                },
            })
    return tool_calls or None


class ClaudeProvider(BaseProvider):
    """Claude Provider，使用 Anthropic SDK。"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.client = anthropic.AsyncAnthropic(api_key=config.api_key)

    async def generate(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        system_text, anthropic_msgs = _to_anthropic_messages(messages)

        kwargs = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": anthropic_msgs,
        }
        if system_text:
            kwargs["system"] = system_text
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)

        resp = await self.client.messages.create(**kwargs)

        content = ""
        for block in resp.content:
            if block.type == "text":
                content += block.text

        return LLMResponse(
            content=content,
            tool_calls=_parse_tool_use(resp),
            raw={"stop_reason": resp.stop_reason, "usage": resp.usage.__dict__ if resp.usage else None},
        )
