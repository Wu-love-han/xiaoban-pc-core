"""`/api/sync`：三端同步（指令 / 日志 / 对话 / 记忆）。

任何终端（PC 自己、手机、ESP32）都调这套接口：
- 注册 + 心跳 → 知道自己在线
- 下发指令 → 目标终端 claim 后执行，回结果
- 写日志 / 按游标拉增量日志
- 拉对话、拉记忆快照

鉴权：与其它 /api 一致（X-PC-Token，配置里的 server.auth_token）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core import sync_hub

from ..auth import require_auth

logger = logging.getLogger("pccore.api.sync")

router = APIRouter(prefix="/api/sync", tags=["sync"], dependencies=[Depends(require_auth)])


class RegisterIn(BaseModel):
    id: str
    name: str = ""
    kind: str = "unknown"
    meta: dict | None = None


class HeartbeatIn(BaseModel):
    id: str


class CommandIn(BaseModel):
    from_: str = "pc"
    to: str
    text: str

    model_config = {"populate_by_name": True}


class CommandResultIn(BaseModel):
    id: int
    ok: bool = True
    result: str = ""


class LogIn(BaseModel):
    tid: str
    kind: str = "info"
    text: str = ""
    data: dict | None = None


@router.get("/state")
async def hub_state():
    try:
        return {"ok": True, "state": sync_hub.state()}
    except Exception as exc:  # noqa: BLE001
        logger.exception("读同步状态失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/register")
async def register(body: RegisterIn):
    try:
        t = sync_hub.register(body.id, body.name, body.kind, body.meta)
        sync_hub.log(body.id, "system", f"终端注册：{body.name or body.id}（{body.kind}）")
        return {"ok": True, "terminal": t}
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("注册终端失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/heartbeat")
async def heartbeat(body: HeartbeatIn):
    try:
        return {"ok": True, "alive": sync_hub.heartbeat(body.id)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/terminals")
async def terminals():
    try:
        items = sync_hub.list_terminals()
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.post("/command")
async def push_command(body: CommandIn):
    try:
        cmd = sync_hub.push_command(body.from_, body.to, body.text)
        return {"ok": True, "command": cmd}
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("下发指令失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/commands")
async def list_commands(
    to: str = Query(default=""),
    limit: int = Query(default=30, ge=1, le=200),
):
    try:
        items = sync_hub.list_commands(limit=limit, to_tid=to)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.get("/commands/claim")
async def claim_commands(tid: str = Query(...), limit: int = Query(default=10, ge=1, le=50)):
    """目标终端领取待执行指令。"""
    try:
        items = sync_hub.claim_commands(tid, limit=limit)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.post("/command/result")
async def command_result(body: CommandResultIn):
    try:
        ok = sync_hub.finish_command(body.id, body.ok, body.result)
        return {"ok": True, "updated": ok}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/log")
async def push_log(body: LogIn):
    try:
        lid = sync_hub.log(body.tid, body.kind, body.text, body.data)
        return {"ok": True, "id": lid}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/logs")
async def pull_logs(since: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200)):
    try:
        items = sync_hub.pull_logs(since, limit)
        return {"ok": True, "items": items, "count": len(items), "cursor": sync_hub.log_cursor()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.get("/conversations")
async def conversations(
    since_ms: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    try:
        items = sync_hub.pull_conversations(since_ms, limit)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.get("/memory")
async def memory():
    try:
        return {"ok": True, "memory": sync_hub.memory_snapshot()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
