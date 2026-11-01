"""`/api/memory/*` —— 记忆+情绪引擎 API。

把 `core.memory_engine` 的纯逻辑包成 HTTP 接口。统一返回
`{"ok": true, ...}` / `{"ok": false, "error": "..."}` 形状，
前端设置抽屉直接消费。

为什么每个端点都自己 try/except：FastAPI 的全局异常处理器虽然会兜底，
但这里希望「记忆坏了不影响聊天」，任何一步出错都返回 ok:false 而不是 500。
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core import memory_engine as mem

from ..auth import require_auth

logger = logging.getLogger("pccore.api.memory")

router = APIRouter(prefix="/api/memory", tags=["memory"], dependencies=[Depends(require_auth)])

# 惰性初始化：main.py 的 lifespan 只调 core.db.init()，没碰 memory.db。
# 这里在第一个请求时补一次建表（幂等，CREATE IF NOT EXISTS），线程安全。
_init_lock = threading.Lock()
_inited = False


def _ensure_engine() -> None:
    global _inited
    if _inited:
        return
    with _init_lock:
        if _inited:
            return
        mem.init()
        _inited = True


class RememberBody(BaseModel):
    """POST /api/memory/remember 的请求体。"""

    content: str = Field(default="", description="要记住的内容")
    category: str = Field(default="通用", description="分类，如 喜好/约定/重要")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="重要度 0-1")


class ForgetBody(BaseModel):
    """POST /api/memory/forget 的请求体。"""

    id: int = Field(..., description="长期记忆的 id")


class MoodBody(BaseModel):
    """POST /api/memory/mood 的请求体（手动调情绪，调试用）。"""

    mood: str = Field(default="calm", description="情绪，如 calm/happy/tired/curious")
    energy: float = Field(default=65.0, ge=0.0, le=100.0, description="精力 0-100")


@router.get("/state")
async def memory_state():
    """GET /api/memory/state → 当前记忆+情绪总览。"""
    try:
        _ensure_engine()
        return {"ok": True, **mem.get_state()}
    except Exception as exc:  # noqa: BLE001
        logger.exception("读记忆总览失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/long-term")
async def memory_long_term():
    """GET /api/memory/long-term → 长期记忆列表。"""
    try:
        _ensure_engine()
        items = mem.list_long_term(limit=100)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("读长期记忆失败")
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.post("/remember")
async def memory_remember(body: RememberBody):
    """POST /api/memory/remember → 手动存一条长期记忆。"""
    try:
        _ensure_engine()
        item = mem.remember_long_term(body.content, body.category, body.importance)
        return {"ok": True, "item": item}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("存长期记忆失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/forget")
async def memory_forget(body: ForgetBody):
    """POST /api/memory/forget → 删除一条长期记忆。"""
    try:
        _ensure_engine()
        deleted = mem.forget_long_term(body.id)
        return {"ok": True, "deleted": deleted}
    except Exception as exc:  # noqa: BLE001
        logger.exception("删除长期记忆失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/mood")
async def memory_mood(body: MoodBody):
    """POST /api/memory/mood → 手动调情绪（调试/测试）。"""
    try:
        _ensure_engine()
        mood = mem.set_mood(body.mood, body.energy)
        return {"ok": True, "mood": mood}
    except Exception as exc:  # noqa: BLE001
        logger.exception("调情绪失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
