"""`GET /api/tools` 与 `GET /api/events`。

`/api/tools` 直接读 `core.toolbase.registry.public_list()`（不含 run，不可执行）。
前端拿它画「能力清单」；brain 拿 schema 喂模型，两边共用同一份注册表，
所以这里**不缓存**——新加工具文件后刷新页面就能看到。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from core import db
from core.toolbase import load_all, registry

from ..auth import require_auth

logger = logging.getLogger("pccore.api.tools")

router = APIRouter(prefix="/api", tags=["tools"], dependencies=[Depends(require_auth)])

MAX_LIMIT = 500


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def ensure_tools_loaded() -> int:
    """保证工具注册表非空，返回工具数量。

    **为什么需要这个兜底**：正常路径是 main.py 的 lifespan 里调 `load_all("tools")`。
    但 lifespan 只在 `with TestClient(app)` 这种上下文管理器用法下才会执行 ——
    pytest 里常见的 `TestClient(app)` 直接实例化、或某些 ASGI 宿主不会跑 lifespan，
    这时注册表是空的，`/api/tools` 返回 `items: []`，看起来像「工具全丢了」。

    `load_all` 是幂等的（按名字覆盖注册），重复调用没有副作用、成本也极低
    （扫一次 tools/*.py 的模块名，已 import 的模块走 sys.modules 缓存）。
    所以这里按需补一次，比让接口静默返回空列表要好。
    """
    try:
        n = len(registry.names())
    except Exception:  # noqa: BLE001
        logger.exception("读工具注册表失败")
        return 0
    if n:
        return n
    try:
        loaded = load_all("tools")
        logger.info("工具注册表为空，已惰性补载：%d 个", loaded)
    except Exception:  # noqa: BLE001
        logger.exception("惰性加载工具失败")
        return len(registry.names())
    return len(registry.names())


@router.get("/tools")
async def list_tools():
    """GET /api/tools → {items:[{name,title,desc,danger,params}]}"""
    try:
        ensure_tools_loaded()
        items = registry.public_list()
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("列工具失败")
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.get("/events")
async def list_events(
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    session_id: str = Query(default=""),
):
    """GET /api/events?limit=50&session_id= → {items:[{id,kind,payload,ts}]}"""
    try:
        items = db.list_events(limit=_clamp(limit, 1, MAX_LIMIT), session_id=session_id or "")
        return {"ok": True, "items": items}
    except Exception as exc:  # noqa: BLE001
        logger.exception("列事件失败")
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}
