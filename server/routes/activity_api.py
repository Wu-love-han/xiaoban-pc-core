"""`/api/activity`：小伴现在在干什么（实时）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core import activity

from ..auth import require_auth

router = APIRouter(prefix="/api/activity", tags=["activity"], dependencies=[Depends(require_auth)])


@router.get("")
async def current():
    try:
        return {"ok": True, **activity.snapshot()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@router.post("/reset")
async def reset():
    try:
        activity.reset()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
