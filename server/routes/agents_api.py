"""`/api/agents/*`：三端 AI 互通。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import agents

from ..auth import require_auth

router = APIRouter(prefix="/api/agents", tags=["agents"], dependencies=[Depends(require_auth)])


class SendIn(BaseModel):
    from_id: str
    to_id: str
    content: str
    kind: str = "note"


@router.get("/state")
async def state():
    try:
        return {"ok": True, **agents.state()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@router.post("/send")
async def send(body: SendIn):
    try:
        r = agents.send(body.from_id, body.to_id, body.content, kind=body.kind)
        return {"ok": True, **r}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@router.get("/inbox")
async def inbox(agent_id: str = "phone", limit: int = 20, unread_only: bool = True):
    try:
        items = agents.inbox(agent_id, limit=limit, unread_only=unread_only)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "items": []}


@router.post("/read")
async def mark_read(agent_id: str = "phone"):
    try:
        n = agents.mark_read(agent_id)
        return {"ok": True, "marked": n}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@router.get("/recent")
async def recent(limit: int = 30):
    try:
        return {"ok": True, "items": agents.recent(limit=limit)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "items": []}
