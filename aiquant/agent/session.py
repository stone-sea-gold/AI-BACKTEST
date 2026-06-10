"""Chat Session 管理 — 持久化 + 滑动窗口压缩。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from aiquant.store.sqlite_store import SQLiteStore


@dataclass
class ChatSession:
    """对话会话。"""
    session_id: str
    messages: list[dict] = field(default_factory=list)
    current_strategy: dict | None = None
    status: str = "active"  # active / completed / aborted
    loop_count: int = 0
    error_signature: str | None = None
    created_at: str = ""
    updated_at: str = ""


def extract_error_signature(error: Exception) -> str:
    """从 Pydantic ValidationError 提取错误签名。"""
    from pydantic import ValidationError
    if isinstance(error, ValidationError) and error.errors():
        first = error.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", []))
        typ = first.get("type", "unknown")
        return f"{loc}_{typ}"
    return str(type(error).__name__)


def build_error_message(error: Exception) -> str:
    """构建用户友好的错误提示。"""
    from pydantic import ValidationError
    if isinstance(error, ValidationError):
        msgs = []
        for e in error.errors()[:3]:
            loc = ".".join(str(x) for x in e.get("loc", []))
            msgs.append(f"- {loc}: {e.get('msg', '')}")
        return "策略 JSON 校验失败，请修正以下问题：\n" + "\n".join(msgs)
    return f"校验失败: {error}"


def build_escalation_message(error: Exception, loop_count: int) -> str:
    """升级错误提示 — 重复错误时更具体。"""
    from pydantic import ValidationError
    if isinstance(error, ValidationError) and error.errors():
        first = error.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", []))
        msg = first.get("msg", "")
        if loop_count >= 2:
            return (
                f"连续多次校验失败。请严格按以下格式修正：\n"
                f"字段 {loc} 的问题：{msg}\n\n"
                f"请参考示例格式重新生成策略 JSON。"
            )
        return f"字段 {loc} 校验失败：{msg}。请仔细修正后重试。"
    return f"重复错误，请修正: {error}"


def compress_messages(messages: list[dict], max_messages: int = 20) -> tuple[list[dict], list[dict]]:
    """滑动窗口压缩，返回 (压缩后消息, 被裁剪的消息)。

    保留策略：
    - 第一条 system prompt 始终保留（锚点）
    - 最近 max_messages // 2 轮保留
    - 中间部分压缩为摘要
    """
    if len(messages) <= max_messages:
        return messages, []

    # 找到第一条 system 消息作为锚点
    anchor_idx = 0
    for i, m in enumerate(messages):
        if m["role"] == "system":
            anchor_idx = i
            break

    anchor = messages[:anchor_idx + 1]
    remaining = messages[anchor_idx + 1:]
    keep_recent = max_messages - len(anchor) - 1  # 留 1 条给摘要

    if keep_recent < 2:
        keep_recent = 2

    archived = remaining[:-keep_recent]
    recent = remaining[-keep_recent:]

    # 构建摘要
    summary_parts = []
    for m in archived:
        if m["role"] == "user":
            content = m["content"][:50]
            summary_parts.append(f"用户：{content}")
    summary_text = "（历史摘要：" + "；".join(summary_parts[-3:]) + "）"

    compressed = anchor + [{"role": "system", "content": summary_text}] + recent
    return compressed, archived
