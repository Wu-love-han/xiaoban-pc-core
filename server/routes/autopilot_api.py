"""`/api/autopilot`：主动行为调度 API。

小伴「自己找事做」的控制面：看调度器状态、增删行为规则、取待发送队列。
所有接口形状统一 `{"ok": true/false, ...}`，鉴权依赖挂在 router 上（同 tools_api）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import autopilot

from ..auth import require_auth

logger = logging.getLogger("pccore.api.autopilot")

router = APIRouter(
    prefix="/api/autopilot", tags=["autopilot"], dependencies=[Depends(require_auth)]
)


class BehaviorIn(BaseModel):
    """POST /api/autopilot/behaviors 的请求体。

    字段全部可选：缺 kind 直接报「行为类型必填」，at/text 没给走默认文案。
    """

    kind: str | None = None
    at: str = ""
    text: str = ""
    interval_minutes: int = 0


@router.get("/status")
async def get_status():
    """GET /api/autopilot/status → 调度器状态。"""
    try:
        return {"ok": True, **autopilot.status()}
    except Exception as exc:  # noqa: BLE001
        logger.exception("读主动行为状态失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/behaviors")
async def list_behaviors():
    """GET /api/autopilot/behaviors → 行为规则列表。"""
    try:
        items = autopilot.list_behaviors()
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("列行为失败")
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.post("/behaviors")
async def add_behavior(body: BehaviorIn):
    """POST /api/autopilot/behaviors → 添加行为，立即唤醒调度线程。"""
    try:
        item = autopilot.add_behavior(
            kind=body.kind or "",
            at=body.at,
            text=body.text,
            interval_minutes=body.interval_minutes,
        )
        autopilot.wake()
        return {"ok": True, "item": item}
    except ValueError as exc:
        logger.warning("添加行为被拒：%s", exc)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("添加行为异常")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.delete("/behaviors/{bid}")
async def delete_behavior(bid: int):
    """DELETE /api/autopilot/behaviors/{id} → 删除行为。"""
    try:
        deleted = autopilot.delete_behavior(bid)
        if not deleted:
            return {"ok": False, "error": f"行为 {bid} 不存在"}
        return {"ok": True, "id": bid}
    except Exception as exc:  # noqa: BLE001
        logger.exception("删除行为失败：%s", bid)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/queue")
async def list_queue():
    """GET /api/autopilot/queue → 待发送队列。"""
    try:
        items = autopilot.list_queue()
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("列待发送队列失败")
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.post("/drain")
async def drain_queue():
    """POST /api/autopilot/drain → 清空队列并返回被清掉的消息（供聊天接口用）。"""
    try:
        items = autopilot.drain_queue()
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("清空队列失败")
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}
