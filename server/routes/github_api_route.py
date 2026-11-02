"""`/api/github`：GitHub 连接（搜索 / 仓库 / Release / 账户）。

用户需求："要什么插件，通过这个搜索，然后我可以登录我的账户"
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core import github_api, plugins as plugin_mod

from ..auth import require_auth

logger = logging.getLogger("pccore.api.github")

router = APIRouter(prefix="/api/github", tags=["github"], dependencies=[Depends(require_auth)])


class InstallIn(BaseModel):
    fullName: str
    tag: str | None = None


@router.get("/status")
async def gh_status():
    try:
        return {"ok": True, "status": github_api.status(), "login": github_api.login_hint()}
    except Exception as exc:  # noqa: BLE001
        logger.exception("读 GitHub 状态失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/search")
async def gh_search(
    q: str = Query(default=""),
    sort: str = Query(default="stars"),
    limit: int = Query(default=20, ge=1, le=50),
    pluginOnly: bool = Query(default=False),
):
    try:
        if pluginOnly:
            res = github_api.search_plugins(q, limit=limit)
        else:
            # 默认也优先插件生态，不够才放宽（search_plugins 内部处理）
            res = github_api.search_plugins(q, limit=limit)
        return res
    except Exception as exc:  # noqa: BLE001
        logger.exception("GitHub 搜索失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/repo")
async def gh_repo(fullName: str = Query(...)):
    try:
        return github_api.repo_info(fullName)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/releases")
async def gh_releases(fullName: str = Query(...)):
    try:
        return github_api.releases(fullName)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/install")
async def gh_install(body: InstallIn):
    """从搜索结果一键装插件：owner/repo 或 owner/repo@tag。"""
    try:
        spec = body.fullName.strip()
        if body.tag:
            spec = f"{spec}@{body.tag.lstrip('v')}" if False else f"{spec}@{body.tag}"
        item = plugin_mod.install(spec)
        return {"ok": True, "item": item}
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("从 GitHub 安装失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
