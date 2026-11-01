"""会话 CRUD（契约第五节）。

注意 `GET /api/sessions/{id}/messages` 要返回 `tool_calls`（JSON 数组），
它是「这句话当时被判成什么」的证据，前端历史渲染要靠它还原工具卡片。
db.list_messages 已经把 TEXT 列解成 list 了，这里原样透出。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core import db

from ..auth import require_auth

logger = logging.getLogger("pccore.api.sessions")

router = APIRouter(prefix="/api/sessions", tags=["sessions"], dependencies=[Depends(require_auth)])

MAX_LIMIT = 500


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


class SessionIn(BaseModel):
    title: str = ""


@router.post("")
async def create_session(body: SessionIn | None = None):
    """POST /api/sessions → {id, title, created_at}"""
    try:
        s = db.create_session(title=(body.title if body else "") or "")
        return {"ok": True, "id": s["id"], "title": s["title"], "created_at": s["created_at"]}
    except Exception as exc:  # noqa: BLE001
        logger.exception("新建会话失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("")
async def list_sessions(limit: int = Query(default=30, ge=1, le=MAX_LIMIT)):
    """GET /api/sessions?limit=30 → {items:[{id,title,updated_at,msg_count}]}"""
    try:
        items = [
            {
                "id": s["id"],
                "title": s.get("title") or "",
                "updated_at": s.get("updated_at") or 0,
                "msg_count": int(s.get("msg_count") or 0),
            }
            for s in db.list_sessions(limit=_clamp(limit, 1, MAX_LIMIT))
        ]
        return {"ok": True, "items": items}
    except Exception as exc:  # noqa: BLE001
        logger.exception("列会话失败")
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.get("/{session_id}/messages")
async def list_messages(session_id: str, limit: int = Query(default=100, ge=1, le=MAX_LIMIT)):
    """GET /api/sessions/{id}/messages?limit=100 → {items:[...]}"""
    try:
        if db.get_session(session_id) is None:
            return {"ok": False, "items": [], "error": "没有这个会话"}
        items = [
            {
                "id": m["id"],
                "role": m["role"],
                "content": m.get("content") or "",
                "thinking": m.get("thinking") or "",
                "tool_calls": m.get("tool_calls") or [],
                "created_at": m.get("created_at") or 0,
                "meta": m.get("meta") or {},
            }
            for m in db.list_messages(session_id, limit=_clamp(limit, 1, MAX_LIMIT))
        ]
        return {"ok": True, "items": items}
    except Exception as exc:  # noqa: BLE001
        logger.exception("列消息失败：%s", session_id)
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """DELETE /api/sessions/{id} → {ok:true}"""
    try:
        if db.get_session(session_id) is None:
            # 幂等：删一个已经不存在的会话不算错误，前端点了两下不该报错。
            return {"ok": True, "deleted": False}
        db.delete_session(session_id)
        return {"ok": True, "deleted": True}
    except Exception as exc:  # noqa: BLE001
        logger.exception("删会话失败：%s", session_id)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
