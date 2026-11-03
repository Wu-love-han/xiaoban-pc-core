"""`/api/dashboard`：后台看板（终端在线、任务日志、指令队列、工具使用）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from core import db, sync_hub

from ..auth import require_auth

logger = logging.getLogger("pccore.api.dashboard")

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_auth)])


@router.get("")
async def dashboard(logs: int = Query(default=30, ge=1, le=200)):
    out: dict = {"ok": True}
    try:
        out["sync"] = sync_hub.state()
        out["terminals"] = sync_hub.list_terminals()
        out["logs"] = sync_hub.pull_logs(0, logs)[-logs:]
        out["commands"] = sync_hub.list_commands(limit=20)
    except Exception:  # noqa: BLE001
        logger.warning("读同步数据失败", exc_info=True)
        out["sync"], out["terminals"], out["logs"], out["commands"] = {}, [], [], []

    try:
        st = db.stats()
        out["db"] = st
        rows = db.query(
            "SELECT session_id, COUNT(*) AS n, MAX(created_at) AS last FROM messages "
            "GROUP BY session_id ORDER BY last DESC LIMIT 10"
        )
        out["recent_sessions"] = [dict(r) for r in rows]
        tr = db.query(
            "SELECT name, COUNT(*) AS n, SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) AS ok_n "
            "FROM tool_runs GROUP BY name ORDER BY n DESC LIMIT 15"
        )
        out["tool_usage"] = [dict(r) for r in tr]
    except Exception:  # noqa: BLE001
        logger.warning("读主库统计失败", exc_info=True)
        out["db"], out["recent_sessions"], out["tool_usage"] = {}, [], []
    return out
