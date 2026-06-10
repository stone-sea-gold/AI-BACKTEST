"""v2 测试：Session 存储与滑动窗口压缩。"""

import tempfile
from pathlib import Path

from aiquant.agent.session import (
    ChatSession,
    compress_messages,
    extract_error_signature,
    build_error_message,
    build_escalation_message,
)
from aiquant.store.sqlite_store import SQLiteStore


def _tmp_store() -> SQLiteStore:
    return SQLiteStore(Path(tempfile.mkdtemp()) / "test.db")


def test_session_create_and_get():
    store = _tmp_store()
    store.create_session("s1", [{"role": "user", "content": "hello"}])
    session = store.get_session("s1")
    assert session is not None
    assert session["session_id"] == "s1"
    assert session["messages"] == [{"role": "user", "content": "hello"}]
    assert session["status"] == "active"


def test_session_update():
    store = _tmp_store()
    store.create_session("s2")
    store.update_session("s2", messages=[{"role": "user", "content": "test"}],
                         status="completed", loop_count=3)
    session = store.get_session("s2")
    assert session["status"] == "completed"
    assert session["loop_count"] == 3
    assert len(session["messages"]) == 1


def test_session_archive_messages():
    store = _tmp_store()
    store.create_session("s3")
    store.archive_messages("s3", [
        {"role": "user", "content": "msg1"},
        {"role": "assistant", "content": "msg2"},
    ])
    msgs = store.get_session_messages("s3")
    assert len(msgs) == 2
    assert msgs[0]["content"] == "msg1"


def test_compress_messages_no_op():
    messages = [{"role": "user", "content": f"msg{i}"} for i in range(5)]
    compressed, archived = compress_messages(messages, max_messages=20)
    assert len(compressed) == 5
    assert len(archived) == 0


def test_compress_messages_with_compression():
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": "a3"},
        {"role": "user", "content": "q4"},
        {"role": "assistant", "content": "a4"},
    ]
    compressed, archived = compress_messages(messages, max_messages=6)
    assert len(compressed) <= 6
    assert len(archived) > 0
    # 第一条 system 消息保留
    assert compressed[0]["role"] == "system"
    assert compressed[0]["content"] == "system prompt"


def test_extract_error_signature():
    from pydantic import BaseModel, field_validator

    class M(BaseModel):
        x: int

        @field_validator("x")
        @classmethod
        def check(cls, v):
            if v < 0:
                raise ValueError("must be positive")
            return v

    try:
        M(x=-1)
    except Exception as e:
        sig = extract_error_signature(e)
        assert "x" in sig
        assert len(sig) > 0


def test_build_error_message():
    from pydantic import BaseModel

    class M(BaseModel):
        x: int

    try:
        M(x="abc")
    except Exception as e:
        msg = build_error_message(e)
        assert "校验失败" in msg
