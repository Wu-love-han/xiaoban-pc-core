"""`/api/capabilities`：能力插槽清单（用户和前端看"现在有什么、未来能插什么"）。

只读，鉴权与其它 /api 一致。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from core import capabilities as cap_mod

from ..auth import require_auth

logger = logging.getLogger("pccore.api.capabilities")

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_capabilities():
    try:
        items = cap_mod.list_capabilities()
        enabled = [c["id"] for c in items if c.get("enabled")]
        planned = [c["id"] for c in items if c.get("planned")]
        return {"ok": True, "items": items, "count": len(items), "enabled": enabled, "planned": planned}
    except Exception as exc:  # noqa: BLE001
        logger.exception("列能力失败")
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}
