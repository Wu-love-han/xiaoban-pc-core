"""`/api/proactive`：主动消息通道（小伴主动开口用）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core import proactive

from ..auth import require_auth

logger = logging.getLogger("pccore.api.proactive")

router = APIRouter(prefix="/api/proactive", tags=["proactive"], dependencies=[Depends(require_auth)])


class PushIn(BaseModel):
    text: str
    kind: str = "note"
    source: str = "manual"
    priority: int = 1


class AckIn(BaseModel):
    id: int | None = None
    all: bool = False


@router.get("/pending")
async def get_pending(limit: int = Query(default=10, ge=1, le=50)):
    try:
        items = proactive.pending(limit)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("读主动消息失败")
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.post("/ack")
async def ack(body: AckIn):
    try:
        if body.all:
            return {"ok": True, "acked": proactive.ack_all()}
        if body.id is None:
            return {"ok": False, "error": "要给 id 或 all=true"}
        return {"ok": True, "acked": 1 if proactive.ack(body.id) else 0}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/push")
async def push(body: PushIn):
    try:
        mid = proactive.push(body.text, body.kind, body.source, body.priority)
        return {"ok": True, "id": mid}
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("推主动消息失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/state")
async def state():
    try:
        return {"ok": True, "state": proactive.state(), "recent": proactive.recent(20)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
