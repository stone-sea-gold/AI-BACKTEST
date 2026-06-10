"""Chat API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aiquant.agent.hub import LLMHub
from aiquant.agent.router import Router
from aiquant.agent.schemas import ChatRequest, ChatResponse, LLMConfigRequest
from aiquant.config.logger import logger
from aiquant.providers.base import LLMConfig
from aiquant.store.sqlite_store import SQLiteStore

router = APIRouter(prefix="/api/v1", tags=["chat"])

store = SQLiteStore()

# 全局 Router 实例（延迟初始化）
_router: Router | None = None


def _get_router() -> Router:
    global _router
    if _router is not None:
        return _router

    config_data = store.get_llm_config()
    if not config_data:
        raise HTTPException(
            status_code=400,
            detail="LLM 未配置，请先调用 POST /api/v1/config/llm 设置 API Key",
        )

    llm_config = LLMConfig(
        provider=config_data["provider"],
        api_key=config_data["api_key"],
        base_url=config_data.get("base_url"),
        model=config_data["model"],
        max_tokens=config_data["max_tokens"],
        temperature=config_data["temperature"],
    )
    hub = LLMHub(configs=[llm_config], strategy="primary_only")
    _router = Router(hub=hub, store=store)
    return _router


def _reset_router():
    """重置全局 Router（配置更新后调用）。"""
    global _router
    _router = None


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """对话接口 — 自然语言 → 策略翻译 → 回测。"""
    try:
        r = _get_router()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Router 初始化失败: {e}")

    try:
        result = await r.process_message(req.message, req.session_id)
        return result
    except Exception as e:
        logger.error(f"Chat 处理异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/llm")
async def save_llm_config(req: LLMConfigRequest):
    """保存 LLM 配置。"""
    store.save_llm_config(req.model_dump())
    _reset_router()
    return {"message": "LLM 配置已保存"}


@router.get("/config/llm")
async def get_llm_config():
    """获取 LLM 配置（API Key 脱敏）。"""
    config = store.get_llm_config()
    if not config:
        return {"configured": False}
    key = config["api_key"]
    masked = key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
    return {
        "configured": True,
        "provider": config["provider"],
        "model": config["model"],
        "api_key_masked": masked,
        "base_url": config.get("base_url"),
    }


@router.get("/sessions")
async def list_sessions(limit: int = 20):
    """查询历史 session 列表。"""
    return {"sessions": store.get_sessions(limit)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """查询单个 session 详情。"""
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"session {session_id} 不存在")
    return session
