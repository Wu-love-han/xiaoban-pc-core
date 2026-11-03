"""`/api/memory/sync`：把记忆库整体下发给手机，离线也能带着记忆。

用户需求：「把记忆库数据全部搬到软件里面、手机本地，这样离线后也有记忆」
「后台修改记忆后，也是 3 端同步」
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Query

from core import memory_engine

from ..auth import require_auth

logger = logging.getLogger("pccore.api.memsync")

router = APIRouter(prefix="/api/memory", tags=["memory"], dependencies=[Depends(require_auth)])

def _fingerprint(items: list[dict]) -> int:
    """用内容算版本号：增删改都会变，手机据此判断要不要重新拉。"""
    import hashlib  # noqa: PLC0415

    h = hashlib.sha1()
    for it in items:
        h.update(f"{it['id']}|{it['content']}|{it['importance']}".encode("utf-8"))
    return int(h.hexdigest()[:12], 16)


@router.get("/sync")
async def sync(since_version: int = Query(default=0), limit: int = Query(default=500, ge=1, le=2000)):
    """返回全量记忆 + 版本号。手机缓存下来，离线时当上下文用。"""
    try:
        memory_engine.init()
        rows = memory_engine.list_long_term(limit)
        items = [
            {
                "id": r.get("id"),
                "content": str(r.get("content") or ""),
                "category": str(r.get("category") or ""),
                "importance": round(float(r.get("importance") or 0), 2),
            }
            for r in rows
        ]
        ver = _fingerprint(items)
        # 版本没变且客户端已有数据 → 只回版本，省流量
        if since_version and since_version == ver:
            return {"ok": True, "version": ver, "changed": False, "items": []}
        return {
            "ok": True,
            "version": ver,
            "changed": True,
            "count": len(items),
            "items": items,
            "synced_at": int(time.time() * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("记忆同步失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "items": []}


@router.get("/version")
async def version():
    try:
        memory_engine.init()
        rows = memory_engine.list_long_term(500)
        items = [{"id": r.get("id"), "content": str(r.get("content") or ""),
                  "importance": round(float(r.get("importance") or 0), 2)} for r in rows]
        return {"ok": True, "version": _fingerprint(items), "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
