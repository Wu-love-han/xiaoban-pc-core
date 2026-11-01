"""直播/抖音能力（预留插槽）。

用户暂时不启用直播，这里只挂一个空 router，保证 main.py 能正常 import。
以后要做时，替换成真正的 /api/live 路由族即可，不需要再改 main.py。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ..auth import require_auth

logger = logging.getLogger("pccore.api.live")

router = APIRouter(prefix="/api/live", tags=["live"], dependencies=[Depends(require_auth)])


@router.get("/state")
async def live_state():
    """占位：直播未启用。"""
    return {
        "ok": True,
        "enabled": False,
        "planned": True,
        "description": "AI 直播 + 虚拟形象 + 抖音等平台接入（预留，用户启用时实现）",
    }
