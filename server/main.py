"""FastAPI 应用装配。

## 顺序是有讲究的（这里踩过一次坑）

1. 先建 app、加 CORS 中间件
2. 再注册所有 `/api/*` 路由
3. **最后**才 `app.mount("/", StaticFiles(...))`

Starlette 的路由是**按注册顺序**匹配的。`mount("/")` 是一个兜底前缀匹配，
如果它先注册，`/api/health` 会被它整个吃掉，变成「找不到文件」404。
所以静态挂载必须是最后一行。

## 为什么异常处理器统一成 `{"ok": false, "error": ...}`

前端所有 fetch 走同一套错误处理：只要 body 里有 `ok:false` 就显示 `error`。
如果让 FastAPI 抛默认的 500 裸栈，前端拿到的是 HTML，`res.json()` 直接炸，
界面上只会显示「后端连不上」，把真正的原因盖掉了。

## 启动期的容错

`core.db.init()` / `core.toolbase.load_all()` 任何一个失败都**只记日志不阻止启动**。
理由：服务起来了至少 `/api/health` 能告诉你哪里坏了；起不来就什么信息都没有。
"""

from __future__ import annotations

import logging
import logging.handlers
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core import config as cfg_mod
from core import db
from core.paths import LOGS_DIR, WEB_DIR, ensure_dirs
from core.toolbase import load_all
from core import plugins as plugin_mod

from .routes import approvals, autopilot_api, capabilities_api, chat, github_api_route, grandlog_api, live_api, memory_api, plugins_api, sessions, sync_api, system, tools_api

logger = logging.getLogger("pccore.server")

APP_NAME = "pc-core"
APP_VERSION = "1.0.0"


# ------------------------------------------------------------------ 日志

def _setup_logging() -> None:
    """按 config.log 配置挂一个滚动文件 handler（幂等，重复调用不叠加）。"""
    try:
        cfg = cfg_mod.load()
    except Exception:  # noqa: BLE001
        cfg = {}
    lcfg = (cfg.get("log") or {}) if isinstance(cfg, dict) else {}

    root = logging.getLogger("pccore")
    level_name = str(lcfg.get("level") or "INFO").upper()
    root.setLevel(getattr(logging, level_name, logging.INFO))
    if any(getattr(h, "_pccore", False) for h in root.handlers):
        return

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh._pccore = True  # type: ignore[attr-defined]
    root.addHandler(sh)

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            LOGS_DIR / "pccore.log",
            maxBytes=int(lcfg.get("max_bytes") or 5_000_000),
            backupCount=int(lcfg.get("backup_count") or 3),
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        fh._pccore = True  # type: ignore[attr-defined]
        root.addHandler(fh)
    except Exception:  # noqa: BLE001 - 日志写不了也不能影响服务
        root.warning("文件日志初始化失败，只输出到控制台", exc_info=True)


# ------------------------------------------------------------------ 生命周期

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：建目录 → 初始化 DB → 加载工具。每一步独立兜底。"""
    _setup_logging()
    app.state.started_at = time.monotonic()
    logger.info("=" * 56)
    logger.info("%s v%s 启动中…", APP_NAME, APP_VERSION)

    try:
        ensure_dirs()
    except Exception:  # noqa: BLE001
        logger.exception("建目录失败")

    try:
        db.init()
        logger.info("数据库就绪：%s", db.stats().get("db_file"))
    except Exception:  # noqa: BLE001
        logger.exception("数据库初始化失败，接口会返回错误而不是崩溃")

    try:
        n = load_all("tools")
        logger.info("工具加载完成：%d 个", n)
    except Exception:  # noqa: BLE001
        logger.exception("工具加载失败，/api/tools 会是空列表")

    try:
        np = plugin_mod.boot_load_all()
        if np:
            logger.info("插件工具加载完成：%d 个", np)
    except Exception:  # noqa: BLE001
        logger.exception("插件工具加载失败")

    try:
        from core import autopilot as autopilot_mod  # noqa: PLC0415

        autopilot_mod.ensure_running()
        logger.info("主动行为调度已启动")
    except Exception:  # noqa: BLE001
        logger.exception("主动行为调度启动失败")

    try:
        from core import memory_engine  # noqa: PLC0415

        memory_engine.init()
        memory_engine.self_check()
    except Exception:  # noqa: BLE001
        logger.exception("记忆引擎初始化失败")

    try:
        from core import daily_review  # noqa: PLC0415

        daily_review.ensure_scheduled()
    except Exception:  # noqa: BLE001
        logger.exception("每日复盘注册失败")

    try:
        from core import sync_hub  # noqa: PLC0415

        sync_hub.init()
        sync_hub.register("pc", "PC（小伴）", "pc", {"role": "hub"})
        sync_hub.log("pc", "system", "PC 中枢启动")
        logger.info("同步中枢就绪（PC 已注册为终端）")
    except Exception:  # noqa: BLE001
        logger.exception("同步中枢初始化失败")

    try:
        cfg = cfg_mod.load()
        srv = (cfg.get("server") or {}) if isinstance(cfg, dict) else {}
        logger.info(
            "监听配置 %s:%s ｜ 鉴权 %s ｜ provider %s/%s",
            srv.get("host") or "127.0.0.1",
            srv.get("port") or 8770,
            "开" if (srv.get("auth_token") or "").strip() else "关",
            (cfg.get("brain") or {}).get("provider"),
            (cfg.get("brain") or {}).get("model"),
        )
    except Exception:  # noqa: BLE001
        pass

    logger.info("%s 就绪", APP_NAME)
    try:
        yield
    finally:
        logger.info("%s 正在退出…", APP_NAME)


def create_app() -> FastAPI:
    app = FastAPI(
        title="pc-core",
        version=APP_VERSION,
        description="小伴 · PC 控制台服务端（契约见 docs/CONTRACT.md）",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    # -------------------------------------------------------------- CORS
    # 本机开发：前端可能从 http://localhost:xxxx 或 file:// 直接打开页面来调接口。
    # 不用 allow_credentials（会与 allow_origins=["*"] 冲突，且我们走自定义头不靠 cookie）。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
        max_age=600,
    )

    # -------------------------------------------------------------- 异常
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        """保留原状态码，body 换成统一形状。"""
        detail = exc.detail
        msg = detail if isinstance(detail, str) else str(detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": msg, "status": exc.status_code},
            headers=getattr(exc, "headers", None) or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        """422 也走统一形状（前端只需要看 error）。"""
        try:
            first = exc.errors()[0]
            loc = ".".join(str(x) for x in first.get("loc") or [])
            msg = f"请求参数不对：{loc} {first.get('msg') or ''}".strip()
        except Exception:  # noqa: BLE001
            msg = "请求参数不对"
        logger.warning("校验失败 %s %s：%s", request.method, request.url.path, msg)
        return JSONResponse(status_code=422, content={"ok": False, "error": msg, "status": 422})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        """兜底：任何未捕获异常都变成 JSON，绝不吐 HTML 裸栈。"""
        logger.exception("未处理异常 %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"服务端内部错误：{type(exc).__name__}: {exc}", "status": 500},
        )

    # -------------------------------------------------------------- 路由
    # 注意：这里每加一行，都必须在 app.mount("/") 之前。
    app.include_router(system.public_router)   # /api/health（不鉴权）
    app.include_router(system.router)          # /api/config
    app.include_router(sessions.router)        # /api/sessions...
    app.include_router(chat.router)            # /api/chat, /api/abort/{sid}
    app.include_router(tools_api.router)       # /api/tools, /api/events
    app.include_router(plugins_api.router)      # /api/plugins（GitHub 插件口）
    app.include_router(memory_api.router)        # /api/memory（记忆+情绪）
    app.include_router(autopilot_api.router)     # /api/autopilot（主动行为）
    app.include_router(capabilities_api.router)   # /api/capabilities（能力插槽）
    app.include_router(grandlog_api.router)       # /api/grandlog（总志）
    app.include_router(github_api_route.router)   # /api/github（GitHub 连接）
    app.include_router(sync_api.router)           # /api/sync（三端同步）
    app.include_router(live_api.router)          # /api/live（直播+形象）
    app.include_router(approvals.router)       # /api/approvals...

    @app.get("/api", include_in_schema=False)
    async def api_root():
        """给手工 curl 一个落脚点，顺便自证「后端活着」。"""
        from .routes.tools_api import ensure_tools_loaded  # noqa: PLC0415

        try:
            n = ensure_tools_loaded()
        except Exception:  # noqa: BLE001
            n = 0
        return {
            "ok": True,
            "app": APP_NAME,
            "version": APP_VERSION,
            "tools": n,
            "docs": "/api/docs",
        }

    # -------------------------------------------------------------- 静态
    _mount_static(app)
    return app


_NO_WEB_HTML = """<!doctype html><meta charset="utf-8"><title>pc-core</title>
<body style="background:#0f1115;color:#9aa4b2;font-family:system-ui,'Microsoft YaHei',sans-serif;padding:48px">
<h1 style="color:#4ec9b0;font-weight:600">pc-core</h1>
<p>前端页面还没就绪（web/index.html 不存在或为空）。</p>
<p>接口探活：<a style="color:#4ec9b0" href="/api/health">/api/health</a>
&nbsp;｜&nbsp; 接口文档：<a style="color:#4ec9b0" href="/api/docs">/api/docs</a></p>
</body>"""


def _mount_static(app: FastAPI) -> None:
    """把 web/ 挂到根路径。**必须是最后一步。**

    `StaticFiles(directory=...)` 在目录不存在时直接抛异常，而前端是并行开发的，
    此刻 web/ 可能还是空的/没建。所以：
      - 目录不存在 → 不挂载，根路径退化成一个说明页（纯内存字符串，**不往 web/ 写任何文件**，
        web/ 是前端的写权限范围）；
      - 目录存在但 index.html 为空/缺失 → 照挂，只是根路径由说明页接管；
      - 其它意外 → 只记日志，/api 完全不受影响。
    """
    try:
        if not WEB_DIR.is_dir():
            logger.warning("静态目录不存在：%s（前端未就绪，/api 不受影响）", WEB_DIR)
            _fallback_root(app, "静态目录还不存在")
            return

        index = WEB_DIR / "index.html"
        ready = index.is_file() and index.stat().st_size > 0

        from starlette.staticfiles import StaticFiles  # noqa: PLC0415

        if not ready:
            logger.warning("web/index.html 缺失或为空（前端未就绪），根路径用说明页代替")
            _fallback_root(app, "web/index.html 还没内容")

        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=ready), name="web")
        logger.info("静态目录已挂载：%s", WEB_DIR)
    except Exception:  # noqa: BLE001
        logger.exception("静态挂载失败，前端页面不可用（/api 不受影响）")
        _fallback_root(app, "静态挂载失败")


def _fallback_root(app: FastAPI, reason: str) -> None:
    """注册根路径说明页（不碰 web/ 目录）。"""
    from fastapi.responses import HTMLResponse  # noqa: PLC0415

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    async def _no_web():
        return HTMLResponse(content=_NO_WEB_HTML)

    logger.info("根路径使用说明页（原因：%s）", reason)


app = create_app()


# ------------------------------------------------------------------ 直接运行

def main() -> None:
    """`python -m server.main` 的入口。读配置里的 host/port（默认 8770）。"""
    import uvicorn

    cfg = cfg_mod.load()
    srv = (cfg.get("server") or {}) if isinstance(cfg, dict) else {}
    uvicorn.run(
        "server.main:app",
        host=str(srv.get("host") or "127.0.0.1"),
        port=int(srv.get("port") or 8770),
        log_level="info",
    )


if __name__ == "__main__":
    main()
