"""`/api/chat`（SSE）与 `/api/abort/{sid}`。

## 这里最要命的一点

`StreamingResponse` 一旦开始 yield，**200 响应头就已经发给浏览器了**。
所以生成器内部再抛异常，客户端收到的不是 500，而是一条被截断的流 —— 前端
会永远停在「思考中」。因此本模块的生成器整体 try/except：任何错误都转成
一帧 `event: error` 再正常 return，绝不把异常抛出生成器边界。

## brain 是**延迟导入**的

`core/brain.py` 由 Lead 并行开发。服务必须能在 brain 还没写完 / 写坏了的情况下
正常启动、其它接口正常、`/api/chat` 返回 error 帧而不是 500 白屏。
所以 `from core import brain` 放在请求处理时（函数体内），而不是模块顶层。

## 用户消息不在这里落库

契约规定本轮的用户消息、assistant 回复、tool_calls 都由 brain 负责写。
服务端只做：解析请求 → 保证会话存在 → 转发事件 → 兜住错误。
重复落库会导致历史里每句话出现两遍。
"""

from __future__ import annotations

import inspect
import logging
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from core import db

from ..auth import require_auth
from ..sse import sse_response

logger = logging.getLogger("pccore.api.chat")

router = APIRouter(prefix="/api", tags=["chat"], dependencies=[Depends(require_auth)])

#: 会话标题取首句前 24 字（契约 3.1）
TITLE_CHARS = 24


class ChatIn(BaseModel):
    """`/api/chat` 请求体（契约 5.1）。

    字段全给默认值：**故意不用 422**。请求体缺字段属于前端 bug，
    但让 `/api/chat` 返回 JSON 422 会直接打断前端的 SSE 解析器，
    界面上表现为「点了发送没反应」。改成在流里回一帧 error，前端有地方显示。
    """

    session_id: str | None = None
    text: str = ""
    model: str | None = None
    reasoning: str | None = None


# ------------------------------------------------------------------ 小工具

def _load_brain() -> Any:
    """延迟导入 core.brain。失败返回 None（不抛）。"""
    try:
        from core import brain  # noqa: PLC0415 - 故意延迟导入，见模块 docstring

        return brain
    except Exception as exc:  # noqa: BLE001
        logger.warning("core.brain 导入失败：%s: %s", type(exc).__name__, exc)
        return None


def _err(message: str) -> tuple[str, dict]:
    """错误帧，并顺手记一条事件，方便 `GET /api/events` 事后查。"""
    try:
        db.add_event("error", {"message": message[:800]})
    except Exception:  # noqa: BLE001
        pass
    return "error", {"message": message}


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _ensure_session(session_id: str | None, text: str) -> str:
    """拿到一个真实存在的会话 id；不存在的旧 id 会被替换成新会话。"""
    sid = (session_id or "").strip()
    if sid:
        try:
            if db.get_session(sid) is not None:
                return sid
        except Exception:  # noqa: BLE001
            logger.exception("查会话失败：%s", sid)
        logger.info("会话 %s 不存在（可能被删了），新建一个", sid)

    title = (text or "").strip().replace("\n", " ")[:TITLE_CHARS]
    return str(db.create_session(title=title)["id"])


# ------------------------------------------------------------------ 事件流

async def _event_stream(body: ChatIn, request: Request) -> AsyncIterator[tuple[str, Any]]:
    """把一次对话转成 (event_name, payload) 流。**永不向外抛异常。**"""
    sid = ""
    brain = None
    started = time.perf_counter()
    try:
        text = (body.text or "").strip()
        if not text:
            yield _err("说的话是空的")
            return

        sid = _ensure_session(body.session_id, text)
        # 契约第四节：session 事件必须第一帧
        yield "session", {"session_id": sid}

        brain = _load_brain()
        if brain is None or not hasattr(brain, "run_turn"):
            yield _err("大脑还没准备好（core.brain 未就绪），服务已起来，稍后再试")
            return

        got_turn_end = False
        try:
            async for name, payload in brain.run_turn(
                session_id=sid,
                text=text,
                model=body.model,
                reasoning=body.reasoning,
            ):
                if not name:
                    continue
                if name == "turn_end":
                    got_turn_end = True
                yield str(name), payload if isinstance(payload, dict) else {"value": payload}
        except Exception as exc:  # noqa: BLE001
            logger.exception("brain.run_turn 异常")
            yield _err(f"大脑跑这一轮出错了：{type(exc).__name__}: {exc}")
            return

        if not got_turn_end:
            # 流干净地结束了但没有 turn_end：前端会一直以为「还在生成」。
            yield _err("本轮没有正常收尾（缺 turn_end），可能是大脑中途退出了")
            return

        logger.info("会话 %s 一轮完成，%.0f ms", sid, (time.perf_counter() - started) * 1000)

    except Exception as exc:  # noqa: BLE001 - 最后一道兜底，绝不让流断在半路
        logger.exception("chat 流异常")
        yield _err(f"服务端出错：{type(exc).__name__}: {exc}")
    finally:
        # 客户端断开 / 流被取消时，顺手叫停大脑，别让它继续空转烧 token。
        # 正常结束也会走到这里；request_abort 对已结束的轮次应当是幂等的空操作。
        if brain is not None and sid:
            try:
                abort = getattr(brain, "request_abort", None)
                if callable(abort):
                    await _maybe_await(abort(sid))
            except Exception:  # noqa: BLE001
                logger.debug("收尾时 request_abort 失败（忽略）", exc_info=True)


# ------------------------------------------------------------------ 路由

@router.post("/chat")
async def chat(body: ChatIn, request: Request):
    """POST /api/chat → text/event-stream（契约第四节）。"""
    return sse_response(_event_stream(body, request), request)


@router.post("/abort/{session_id}")
async def abort(session_id: str):
    """POST /api/abort/{sid} → 让正在跑的这一轮停下来。"""
    brain = _load_brain()
    fn = getattr(brain, "request_abort", None) if brain is not None else None
    if not callable(fn):
        return {"ok": False, "error": "大脑还没准备好（core.brain 未就绪），没什么可停的"}
    try:
        await _maybe_await(fn(session_id))
        return {"ok": True, "session_id": session_id}
    except Exception as exc:  # noqa: BLE001
        logger.exception("request_abort 失败：%s", session_id)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
