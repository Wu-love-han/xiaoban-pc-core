"""`/api/consent`：人工确认（AI 改底线文件、删东西等需要用户点头的事）。

安全设计（关键）：
- **approve / deny 只接受本机回环请求**（PC 上的浏览器）。
  手机 App、Tailscale、局域网一律 403——防止手机端 AI 自己批自己。
- AI 只能 create（发起）和查状态，永远拿不到 approve 权限。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from core import consent

from ..auth import is_loopback, require_auth

logger = logging.getLogger("pccore.api.consent")

router = APIRouter(prefix="/api/consent", tags=["consent"], dependencies=[Depends(require_auth)])


class CreateIn(BaseModel):
    kind: str = "other"
    target: str = ""
    detail: str = ""


class DecideIn(BaseModel):
    id: str


def require_loopback(request: Request) -> None:
    """只有本机回环能调（批准/拒绝必须由人在电脑上操作）。"""
    if not is_loopback(request):
        logger.warning("拒绝非本机访问确认接口：%s", request.client.host if request.client else "?")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="确认操作只能在电脑本机的后台看板里做",
        )


@router.post("/create")
async def create(body: CreateIn):
    try:
        req = consent.create(body.kind, body.target, body.detail)
        return {"ok": True, "request": req}
    except Exception as exc:  # noqa: BLE001
        logger.exception("创建确认失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/pending")
async def pending():
    try:
        items = consent.pending()
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.get("/get")
async def get(id: str):
    try:
        item = consent.get(id)
        return {"ok": item is not None, "item": item}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/approve", dependencies=[Depends(require_loopback)])
async def approve(body: DecideIn):
    ok = consent.approve(body.id, by="user")
    return {"ok": ok, "id": body.id, "status": "approved" if ok else "unchanged"}


@router.post("/deny", dependencies=[Depends(require_loopback)])
async def deny(body: DecideIn):
    ok = consent.deny(body.id, by="user")
    return {"ok": ok, "id": body.id, "status": "denied" if ok else "unchanged"}


@router.get("/state")
async def state():
    try:
        return {"ok": True, "state": consent.state()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
