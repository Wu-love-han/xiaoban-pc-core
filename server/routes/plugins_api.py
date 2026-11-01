"""`/api/plugins`：GitHub 插件口。

安装 / 卸载 / 列表 / 重载。全部走鉴权（admin 级控制面）。

POST /api/plugins/install  {"spec": "owner/repo" 或 GitHub 链接}
POST /api/plugins/uninstall {"id": "xxx"}
POST /api/plugins/reload   {"id": "xxx"}（可选，不传 reload 全部）
GET  /api/plugins
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import plugins as plugin_mod

from ..auth import require_auth

logger = logging.getLogger("pccore.api.plugins")

router = APIRouter(prefix="/api/plugins", tags=["plugins"], dependencies=[Depends(require_auth)])


class InstallIn(BaseModel):
    spec: str


class UninstallIn(BaseModel):
    id: str


class ReloadIn(BaseModel):
    id: str | None = None


class MarketIn(BaseModel):
    url: str | None = None


@router.get("")
async def list_plugins():
    try:
        items = plugin_mod.list_plugins()
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("列插件失败")
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.post("/install")
async def install_plugin(body: InstallIn):
    try:
        item = plugin_mod.install(body.spec)
        return {"ok": True, "item": item}
    except (ValueError, RuntimeError) as exc:
        logger.warning("插件安装失败：%s", exc)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("插件安装异常")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/uninstall")
async def uninstall_plugin(body: UninstallIn):
    try:
        res = plugin_mod.uninstall(body.id)
        return {"ok": True, **res}
    except (ValueError, RuntimeError) as exc:
        logger.warning("插件卸载失败：%s", exc)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("插件卸载异常")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/market")
async def get_market():
    """拉取插件市场目录（可加 ?url= 覆盖）。"""
    from fastapi import Request

    # 简单起见，市场 URL 从 query 读
    return await _market_impl()


async def _market_impl(url: str | None = None):
    try:
        data = plugin_mod.market_index(url)
        return {"ok": True, "plugins": data.get("plugins", []) if isinstance(data, dict) else []}
    except Exception as exc:  # noqa: BLE001
        logger.warning("拉取市场目录失败：%s", exc)
        return {"ok": False, "plugins": [], "error": f"{type(exc).__name__}: {exc}"}


@router.post("/reload")
async def reload_plugins(body: ReloadIn | None = None):
    try:
        if body is not None and body.id:
            n = plugin_mod.reload_plugin_tools(body.id)
            return {"ok": True, "id": body.id, "tools": n}
        n = plugin_mod.boot_load_all()
        return {"ok": True, "tools": n}
    except Exception as exc:  # noqa: BLE001
        logger.exception("插件重载异常")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
