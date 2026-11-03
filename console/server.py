"""小伴控制台（独立进程，端口 8771）。

为什么单独一个程序：
用户要求「后台权限最高，而且 AI 进不来」。主 API（8770）是给 AI 用的，
这里（8771）只给「人」用。AI 的工具集里没有 curl / HTTP 客户端，
白名单也只放只读命令，所以结构上够不到这个端口。

鉴权：PIN（config.json 的 server.console_pin），首次启动自动生成 6 位数字。
登录后发一个 HttpOnly cookie，有效期 12 小时。
"""

from __future__ import annotations

import json
import logging
import secrets
import sys
import time
from pathlib import Path

# 让 console/ 能 import 到 core/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import Cookie, FastAPI, HTTPException, Request, Response  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from core import config as cfg_mod  # noqa: E402
from core import db, memory_engine, persona, proactive, sync_hub  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("pccore.console")

CONSOLE_PORT = 8771
COOKIE = "pc_console"
_sessions: dict[str, float] = {}   # token → 过期时间
SESSION_TTL = 12 * 3600

app = FastAPI(title="小伴控制台", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------- PIN

def _pin() -> str:
    """取/生成控制台 PIN。"""
    try:
        cfg = cfg_mod.load()
        srv = cfg.get("server") or {}
        pin = str(srv.get("console_pin") or "").strip()
        if pin:
            return pin
    except Exception:  # noqa: BLE001
        pass
    # 没配就生成一个，写进 config.json
    pin = "".join(secrets.choice("0123456789") for _ in range(6))
    try:
        path = ROOT / "config" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg.setdefault("server", {})["console_pin"] = pin
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        logger.warning("已生成控制台 PIN：%s（写进 config.json 的 server.console_pin）", pin)
    except Exception:  # noqa: BLE001
        logger.exception("写 PIN 失败")
    return pin


def _check(cookie: str | None) -> bool:
    if not cookie:
        return False
    exp = _sessions.get(cookie, 0)
    if exp < time.time():
        _sessions.pop(cookie, None)
        return False
    return True


def _guard(cookie: str | None) -> None:
    if not _check(cookie):
        raise HTTPException(status_code=401, detail="未登录")


# ---------------------------------------------------------------- 页面

@app.get("/", response_class=HTMLResponse)
async def index(pc_console: str | None = Cookie(default=None)):
    return HTMLResponse(PAGE)


class LoginIn(BaseModel):
    pin: str


@app.post("/api/login")
async def login(body: LoginIn, response: Response):
    if body.pin.strip() != _pin():
        await asyncio_sleep(0.4)
        return {"ok": False, "error": "PIN 不对"}
    tok = secrets.token_urlsafe(24)
    _sessions[tok] = time.time() + SESSION_TTL
    response.set_cookie(COOKIE, tok, httponly=True, max_age=SESSION_TTL, samesite="lax")
    return {"ok": True}


@app.post("/api/logout")
async def logout(response: Response, pc_console: str | None = Cookie(default=None)):
    if pc_console:
        _sessions.pop(pc_console, None)
    response.delete_cookie(COOKIE)
    return {"ok": True}


async def asyncio_sleep(s: float) -> None:
    import asyncio  # noqa: PLC0415

    await asyncio.sleep(s)


# ---------------------------------------------------------------- 状态

@app.get("/api/state")
async def state(pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    out: dict = {"ok": True, "at": time.strftime("%Y-%m-%d %H:%M:%S")}

    # 三端
    try:
        out["terminals"] = sync_hub.list_terminals()
    except Exception:  # noqa: BLE001
        out["terminals"] = []

    # PC 在干嘛
    try:
        from tools import _desktop_common as D  # noqa: PLC0415

        out["pc"] = {
            "foreground": D.foreground_title(),
            "windows": [w.get("title") for w in D.list_windows()[:8]],
        }
    except Exception:  # noqa: BLE001
        out["pc"] = {}

    # 手机在干嘛
    try:
        from tools import _adb_common as A  # noqa: PLC0415

        if A.app_ready():
            ok, data = A._app_request("/foreground")  # noqa: F401
            out["phone"] = {
                "online": True,
                "foreground": (data or {}).get("package", "") if ok else "",
                "accessibility": True,
                "shell": A.app_shell_info().get("level", ""),
            }
        else:
            out["phone"] = {"online": False}
    except Exception:  # noqa: BLE001
        out["phone"] = {"online": False}

    # 机器人
    try:
        robots = [t for t in out["terminals"] if t.get("kind") == "robot"]
        out["robot"] = robots[0] if robots else {"online": False, "name": "（未接入）"}
    except Exception:  # noqa: BLE001
        out["robot"] = {}

    # 任务 / 待确认 / 主动消息
    try:
        rows = db.query(
            "SELECT id, title, updated_at FROM sessions ORDER BY updated_at DESC LIMIT 10"
        )
        out["sessions"] = [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        out["sessions"] = []
    try:
        from core import consent  # noqa: PLC0415

        out["consent"] = consent.pending()
    except Exception:  # noqa: BLE001
        out["consent"] = []
    try:
        out["proactive"] = proactive.state()
    except Exception:  # noqa: BLE001
        out["proactive"] = {}

    return out


# ---------------------------------------------------------------- 取消任务

class CancelIn(BaseModel):
    session_id: str


@app.post("/api/task/cancel")
async def cancel(body: CancelIn, pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    try:
        from core import brain  # noqa: PLC0415

        brain.request_abort(body.session_id)
        proactive.push(f"你从控制台中断了会话 {body.session_id[:12]}", kind="notice", source="console")
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------- 记忆

@app.get("/api/memory")
async def memory_list(q: str = "", limit: int = 30, pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    try:
        memory_engine.init()
        rows = memory_engine.recall_long_term(q, limit=limit) if q else memory_engine.list_long_term(limit)
        return {"ok": True, "items": [dict(r) for r in rows]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "items": []}


class MemIn(BaseModel):
    id: int
    content: str = ""
    category: str = ""
    importance: float | None = None


@app.post("/api/memory/update")
async def memory_update(body: MemIn, pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    try:
        memory_engine.init()
        ok = memory_engine.update_long_term(body.id, body.content, body.category, body.importance)
        return {"ok": ok}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


class MemDelIn(BaseModel):
    id: int


@app.post("/api/memory/forget")
async def memory_forget(body: MemDelIn, pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    try:
        memory_engine.init()
        return {"ok": memory_engine.forget_long_term(body.id)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------- 人格

@app.get("/api/persona")
async def persona_get(pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    try:
        from core.paths import PERSONA_FILE  # noqa: PLC0415

        return {"ok": True, "text": PERSONA_FILE.read_text(encoding="utf-8")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "text": ""}


class PersonaIn(BaseModel):
    text: str


@app.post("/api/persona")
async def persona_set(body: PersonaIn, pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    try:
        from core.paths import PERSONA_FILE  # noqa: PLC0415

        bak = PERSONA_FILE.with_suffix(".md.bak-" + str(int(time.time())))
        if PERSONA_FILE.exists():
            bak.write_text(PERSONA_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        PERSONA_FILE.write_text(body.text, encoding="utf-8")
        persona.reload()
        proactive.push("人格设定改好了，下一轮就生效。", kind="notice", source="console")
        return {"ok": True, "backup": bak.name}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------- 人机对话

CONSOLE_SESSION_TITLE = "控制台对话"


def _console_session() -> str:
    db.init()
    rows = db.query("SELECT id FROM sessions WHERE title=? ORDER BY created_at DESC LIMIT 1",
                    (CONSOLE_SESSION_TITLE,))
    if rows:
        return rows[0]["id"]
    return db.create_session(CONSOLE_SESSION_TITLE)["id"]


@app.get("/api/chat")
async def chat_history(pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    try:
        sid = _console_session()
        return {"ok": True, "session_id": sid, "items": db.list_messages(sid, limit=40)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "items": []}


class ChatIn(BaseModel):
    text: str


@app.post("/api/chat")
async def chat_send(body: ChatIn, pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    text = (body.text or "").strip()
    if not text:
        return {"ok": False, "error": "空消息"}
    try:
        from core import brain  # noqa: PLC0415

        sid = _console_session()
        r = await brain.run_once(sid, text)
        return {"ok": True, "reply": r.get("text") or "", "tools": [
            {"name": c.get("name"), "args": c.get("args")} for c in (r.get("tool_calls") or [])
        ]}
    except Exception as exc:  # noqa: BLE001
        logger.exception("控制台对话失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------- 消息中心（各端上报）

@app.get("/api/inbox")
async def inbox(limit: int = 30, pc_console: str | None = Cookie(default=None)):
    """所有端上报的消息：主动提醒、资源告警、手机/机器人报告、待确认。"""
    _guard(pc_console)
    items: list[dict] = []
    try:
        for m in proactive.recent(limit):
            items.append({
                "id": "p" + str(m.get("id")),
                "kind": m.get("kind") or "note",
                "source": m.get("source") or "",
                "text": m.get("text") or "",
                "priority": m.get("priority") or 1,
                "ts": m.get("ts_ms") or 0,
                "acked": bool(m.get("ack_ms")),
                "type": "message",
            })
    except Exception:  # noqa: BLE001
        pass
    try:
        from core import consent  # noqa: PLC0415

        for c in consent.pending():
            items.append({
                "id": "c" + str(c.get("id")),
                "kind": "consent",
                "source": "consent",
                "text": f"{c.get('target')}：{(c.get('detail') or '')[:200]}",
                "priority": 3,
                "ts": c.get("created_ms") or 0,
                "consent_id": c.get("id"),
                "type": "consent",
            })
    except Exception:  # noqa: BLE001
        pass
    items.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return {"ok": True, "items": items[:limit], "count": len(items)}


class InboxSendIn(BaseModel):
    text: str
    to: str = "all"


@app.post("/api/inbox/send")
async def inbox_send(body: InboxSendIn, pc_console: str | None = Cookie(default=None)):
    """从控制台给某个端下指令 / 回话。"""
    _guard(pc_console)
    text = (body.text or "").strip()
    if not text:
        return {"ok": False, "error": "空消息"}
    try:
        from core import sync_hub  # noqa: PLC0415

        target = (body.to or "all").strip()
        if target == "all":
            # 广播：写进主动消息 + 三端日志
            proactive.push(text, kind="notice", source="console", priority=2)
            sync_hub.log("console", "command", text[:200])
            return {"ok": True, "sent_to": "all"}
        # 指定端：走指令队列
        cmd = sync_hub.push_command("console", target, text)
        return {"ok": True, "sent_to": target, "command": cmd}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


class AckIn(BaseModel):
    id: int


@app.post("/api/inbox/ack")
async def inbox_ack(body: AckIn, pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    try:
        return {"ok": proactive.ack(body.id)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------- 文档传输

CONSOLE_DOCS = ROOT / "data" / "console_docs"


@app.get("/api/docs")
async def docs_list(pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    CONSOLE_DOCS.mkdir(parents=True, exist_ok=True)
    items = []
    for f in sorted(CONSOLE_DOCS.iterdir(), key=lambda x: -x.stat().st_mtime):
        if f.is_file():
            items.append({
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": int(f.stat().st_mtime * 1000),
            })
    return {"ok": True, "items": items, "dir": str(CONSOLE_DOCS)}


@app.post("/api/docs/upload")
async def docs_upload(request: Request, pc_console: str | None = Cookie(default=None)):
    """接收上传的文档（multipart/form-data）。"""
    _guard(pc_console)
    CONSOLE_DOCS.mkdir(parents=True, exist_ok=True)
    try:
        form = await request.form()
        saved = []
        for key in form.keys():
            up = form[key]
            if hasattr(up, "filename") and up.filename:
                safe = "".join(c for c in up.filename if c not in '\\/:*?"<>|')[:120]
                if not safe:
                    continue
                dest = CONSOLE_DOCS / safe
                content = await up.read()
                dest.write_bytes(content)
                saved.append({"name": safe, "size": len(content)})
        return {"ok": True, "saved": saved}
    except Exception as exc:  # noqa: BLE001
        logger.exception("上传失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.get("/api/docs/download")
async def docs_download(name: str, pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    from fastapi.responses import FileResponse  # noqa: PLC0415

    safe = "".join(c for c in name if c not in '\\/:*?"<>|')
    f = CONSOLE_DOCS / safe
    if not f.exists():
        return JSONResponse({"ok": False, "error": "没有这个文件"}, status_code=404)
    return FileResponse(str(f), filename=safe)


# ---------------------------------------------------------------- 确认

class DecideIn(BaseModel):
    id: str


@app.post("/api/consent/approve")
async def consent_approve(body: DecideIn, pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    from core import consent  # noqa: PLC0415

    return {"ok": consent.approve(body.id, by="console")}


@app.post("/api/consent/deny")
async def consent_deny(body: DecideIn, pc_console: str | None = Cookie(default=None)):
    _guard(pc_console)
    from core import consent  # noqa: PLC0415

    return {"ok": consent.deny(body.id, by="console")}


PAGE = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


def main() -> None:
    import uvicorn  # noqa: PLC0415

    pin = _pin()
    logger.info("=" * 56)
    logger.info("小伴控制台启动：http://0.0.0.0:%s", CONSOLE_PORT)
    logger.info("PIN：%s（在 config.json 的 server.console_pin）", pin)
    logger.info("=" * 56)
    uvicorn.run(app, host="0.0.0.0", port=CONSOLE_PORT, log_level="warning")


if __name__ == "__main__":
    main()
