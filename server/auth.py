"""鉴权：X-PC-Token 请求头校验。

设计取舍：
- **默认不设防。** `config.server.auth_token` 为空 = 不校验。这是本机开发态，
  前端从 localStorage 里读不到 token 也不会被拦。要在局域网/手机上用时把 token 填上。
- **只保护 /api 的业务接口。** `/api/health` 永远放行 —— 它是前端的探活接口，
  挂掉 token 会让「后端连不上」和「token 不对」两种情况在前端长得一模一样，没法排查。
- **token 每次请求重读配置**（config.load() 带 mtime 缓存，开销可忽略），
  这样改 config.json 不用重启服务。
- 比较用 `hmac.compare_digest`，避免按字节短路泄漏长度信息。

用法：
    router = APIRouter(dependencies=[Depends(require_auth)])
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException, Request, status

from core import config as cfg_mod

logger = logging.getLogger("pccore.auth")

HEADER_NAME = "X-PC-Token"


def expected_token() -> str:
    """当前配置里的 token；空串 = 不校验。"""
    try:
        return str(((cfg_mod.load().get("server") or {}).get("auth_token")) or "").strip()
    except Exception:  # noqa: BLE001 - 配置坏掉也不能让鉴权模块把服务拖死
        logger.exception("读取 auth_token 失败，按不校验处理")
        return ""


def auth_enabled() -> bool:
    return bool(expected_token())


def _presented(request: Request, x_pc_token: str | None) -> str:
    """从请求里取客户端给的 token。

    主用契约规定的 `X-PC-Token`；顺手兼容 `Authorization: Bearer xxx`，
    方便 curl / 第三方前端接入，不影响契约。
    """
    if x_pc_token:
        return x_pc_token.strip()
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


async def require_auth(
    request: Request,
    x_pc_token: str | None = Header(default=None, alias=HEADER_NAME),
) -> None:
    """FastAPI 依赖：校验不过直接 401。

    401 的响应体由 main.py 的异常处理器统一改写成 `{"ok": false, "error": ...}`。
    """
    want = expected_token()
    if not want:
        return

    got = _presented(request, x_pc_token)
    if got and hmac.compare_digest(got, want):
        return

    logger.warning("鉴权失败：%s %s", request.method, request.url.path)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="X-PC-Token 缺失或不对",
        headers={"WWW-Authenticate": "X-PC-Token"},
    )


__all__ = ["require_auth", "auth_enabled", "expected_token", "HEADER_NAME"]
