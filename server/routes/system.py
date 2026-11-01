"""`/api/health` 与 `/api/config`（契约第五节）。

## health 为什么不鉴权

它是前端的探活口。如果探活也要 token，那么「后端没起来」和「token 配错了」
在前端看起来完全一样，排查成本极高。所以 health 永远 200，把真实状态写进 body。

## health 为什么必须**永不抛异常**

前端靠它点亮状态灯。它一旦 500，整个界面就显示「后端连不上」，
而实际上后端活得好好的。所以每个字段都单独 try 兜住。

## config POST 只放三个键

`brain.provider` / `brain.model` / `brain.reasoning`。
其它键（尤其是 auth_token、base_url、shell 白名单）不给改 ——
这些是「改错了会把自己锁在门外」的配置，只允许手改 config.json。
改完必须 `core.providers.reset()`，否则 provider 缓存里的旧实例还在用旧 base_url。
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import config as cfg_mod
from core import db
from core.toolbase import registry

from ..auth import auth_enabled, require_auth

logger = logging.getLogger("pccore.api.system")

#: 进程启动时刻（模块在 app 装配时导入，≈ 服务启动）
_START = time.monotonic()

#: POST /api/config 允许改的键（白名单）
EDITABLE_BRAIN_KEYS = ("provider", "model", "reasoning")
VALID_REASONING = ("none", "high", "max")

#: 无鉴权的路由组
public_router = APIRouter(prefix="/api", tags=["system"])
#: 需要鉴权的路由组
router = APIRouter(prefix="/api", tags=["system"], dependencies=[Depends(require_auth)])


def _hdr(s: str) -> str:
    """把任意文本安全地塞进 HTTP 头。

    HTTP 头的值只允许 latin-1 字节，中文直接放进去会在 JSONResponse
    构造时抛 `UnicodeEncodeError`（响应都还没发出去就 500）。
    这里统一 percent-encode，前端要看就 decodeURIComponent。
    """
    return quote((s or "")[:300], safe="")


class ConfigIn(BaseModel):
    """三个字段都可选；只处理传了的。"""

    provider: str | None = None
    model: str | None = None
    reasoning: str | None = None


# ------------------------------------------------------------------ health

def _db_health() -> dict:
    try:
        st = db.stats()
        return {
            "ok": True,
            "file": st.get("db_file"),
            "sessions": st.get("sessions", 0),
            "messages": st.get("messages", 0),
            "tool_runs": st.get("tool_runs", 0),
            "pending_approvals": len(db.list_approvals("pending", limit=50)),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("健康检查读库失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _brain_ready() -> bool:
    """brain 模块能不能导入（前端状态灯用，不算错误）。"""
    try:
        from core import brain  # noqa: PLC0415

        return hasattr(brain, "run_turn")
    except Exception:  # noqa: BLE001
        return False


@public_router.get("/health")
async def health():
    """GET /api/health → {ok, provider, model, tools, db, uptime_s}

    `tools` 是工具**数量**（前端顶栏显示「工具数」）；工具明细走 /api/tools。
    """
    try:
        cfg = cfg_mod.load()
    except Exception:  # noqa: BLE001
        cfg = {}
    bcfg = (cfg.get("brain") or {}) if isinstance(cfg, dict) else {}

    try:
        # 与 /api/tools 共用同一层惰性兜底：lifespan 没跑（TestClient 等）也能拿到真实数量
        from .tools_api import ensure_tools_loaded  # noqa: PLC0415 - 避免循环导入

        n_tools = ensure_tools_loaded()
        names = registry.names()
    except Exception:  # noqa: BLE001
        logger.exception("健康检查读工具注册表失败")
        names, n_tools = [], 0

    dbh = _db_health()
    return {
        "ok": bool(dbh.get("ok")),
        "provider": str(bcfg.get("provider") or "gateway"),
        "model": str(bcfg.get("model") or ""),
        "reasoning": str(bcfg.get("reasoning") or "none"),
        "tools": int(n_tools),
        "tools_count": int(n_tools),
        "tool_names": names,
        "db": dbh,
        "uptime_s": round(time.monotonic() - _START, 1),
        "auth": auth_enabled(),
        "brain_ready": _brain_ready(),
        "ts": int(time.time() * 1000),
    }


# ------------------------------------------------------------------ config

@router.get("/config")
async def get_config():
    """GET /api/config → **顶层直接是**脱敏后的配置对象（契约第五节）。

    注意形状：不是 `{"ok": true, "config": {...}}`，而是直接
    `{"server": {...}, "brain": {...}, ...}`。
    前端 `applyConfig(cfg)` 里读的是 `cfg.brain.model`，包一层就拿不到了。
    """
    try:
        return cfg_mod.redacted()
    except Exception as exc:  # noqa: BLE001
        logger.exception("读配置失败")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"{type(exc).__name__}: {exc}"},
        )


@router.post("/config")
async def patch_config(body: ConfigIn | None = None):
    """POST /api/config → 改 brain.provider/model/reasoning，返回**脱敏后的新配置对象**。

    与 GET 同形状：顶层直接是配置，前端 `applyConfig()` 拿到就能用。
    契约第五节写的是「更新后的配置」，所以不额外包 `{ok, config}`。

    - `model` 允许任意字符串（前端可手填模型名），不做白名单；
    - `reasoning` 只认 none/high/max，传别的忽略（记在响应头 X-Config-Note 里，不污染配置对象）。
    """
    values: dict[str, Any] = {}
    notes: list[str] = []

    if body is not None:
        if body.provider is not None:
            p = body.provider.strip()
            if p:
                values["provider"] = p
        if body.model is not None:
            m = body.model.strip()
            if m:
                values["model"] = m
        if body.reasoning is not None:
            r = body.reasoning.strip().lower()
            if r in VALID_REASONING:
                values["reasoning"] = r
            elif r:
                notes.append(f"reasoning 只支持 {'/'.join(VALID_REASONING)}，已忽略 {r!r}")

    if not values:
        # 没有可改的字段：仍是成功（幂等），返回当前配置 + 说明头
        logger.info("配置未变更（无可改字段）：%s", notes or "空请求")
        return JSONResponse(
            content=cfg_mod.redacted(),
            headers={"X-Config-Changed": "0", "X-Config-Note": _hdr("；".join(notes))},
        )

    try:
        cfg_mod.patch("brain", values)
    except Exception as exc:  # noqa: BLE001
        logger.exception("写配置失败")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"{type(exc).__name__}: {exc}"},
        )

    # 配置变了 → 丢掉 provider 缓存实例，下一轮按新配置重建
    provider_reset = True
    try:
        from core import providers  # noqa: PLC0415

        providers.reset()
    except Exception as exc:  # noqa: BLE001
        provider_reset = False
        logger.warning("providers.reset() 失败：%s: %s", type(exc).__name__, exc)

    logger.info("配置已更新：%s（provider 缓存已清=%s）", values, provider_reset)
    return JSONResponse(
        content=cfg_mod.redacted(),
        headers={
            "X-Config-Changed": "1",
            "X-Config-Updated": ",".join(sorted(values)),
            "X-Config-Note": _hdr("；".join(notes)),
        },
    )
