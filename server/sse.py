"""SSE 编码与心跳包装。

为什么单独一个文件：SSE 的坑全集中在两处 —— **帧格式** 和 **连接生命周期**。

帧格式：前端是手工按 `event:` / `data:` 行切帧再 JSON.parse 的。
`data:` 段里只要混进一个裸换行，整个流的解析就会错位（后面的帧全被当成上一帧的数据）。
所以编码函数保证 data 段永远是**单行** JSON：
  - json.dumps 默认把内容里的 \\n 转义成两个字符，这本来就是安全的；
  - 这里再加一道防御性 replace，防止以后有人换成 indent=2 之类的参数。

连接生命周期：两个协程 + 一个队列。
  - 生产协程：把业务异步生成器的事件编码后丢进队列；
  - 心跳协程：空闲满 15 秒丢一个 `: ping` 注释帧，同时负责探测客户端断连
    （用户关掉页面后 `request.is_disconnected()` 变真，必须主动退出，
    否则这个协程会永远挂在 uvicorn 里，把 worker 拖死）；
  - 消费方就是 StreamingResponse 的生成器本体，只做 `await queue.get()`。
刻意不在消费方用 `asyncio.wait_for(queue.get(), ...)` 做超时：那种写法在
超时与入队同时发生时可能丢帧，让生产方负责心跳就没有这个竞态。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator

from starlette.requests import Request
from starlette.responses import StreamingResponse

logger = logging.getLogger("pccore.sse")

#: 空闲多久发一次心跳（契约第四节：15 秒）
HEARTBEAT_S = 15.0
#: 断连探测间隔。越小关页面后资源释放越快，1 秒足够。
DISCONNECT_POLL_S = 1.0

_DONE = ("__done__", None)


# ------------------------------------------------------------------ 编码

def dumps(payload: Any) -> str:
    """把 payload 压成单行 JSON 字符串（永不抛异常）。"""
    try:
        return json.dumps(
            {} if payload is None else payload,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return json.dumps({"message": str(payload)}, ensure_ascii=False)


def encode_event(name: str, payload: Any = None) -> str:
    """一帧完整的 SSE 事件。

    `event: xxx\\ndata: {单行 JSON}\\n\\n`
    """
    data = dumps(payload)
    # 防御：JSON 序列化结果本不该有裸 CR/LF，这里再兜一次，保证 data 段绝对单行。
    data = data.replace("\r", "\\r").replace("\n", "\\n")
    return f"event: {name}\ndata: {data}\n\n"


def encode_ping() -> str:
    """心跳：SSE 注释行，浏览器/前端解析器会忽略它，但代理不会当流结束。"""
    return ": ping\n\n"


# ------------------------------------------------------------------ 心跳包装

async def _is_disconnected(request: Request | None) -> bool:
    """客户端断连探测。拿不到 request（比如单测）就当没断。"""
    if request is None:
        return False
    try:
        return bool(await request.is_disconnected())
    except Exception:  # noqa: BLE001 - 探测本身失败不该影响推流
        return False


async def heartbeat_wrap(
    events: AsyncIterator[tuple[str, Any]],
    request: Request | None = None,
    *,
    heartbeat_s: float = HEARTBEAT_S,
    poll_s: float = DISCONNECT_POLL_S,
) -> AsyncIterator[str]:
    """给 (event_name, payload) 异步流套上心跳与断连处理，产出 SSE 文本帧。

    - 生产协程整体 try/except：业务里抛异常不会让流断在半路，
      而是补一帧 `error` 再正常结束（此时响应头早就发出去了，改不了状态码）。
    - 客户端断开 → 停止并取消两个协程。
    """
    queue: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()
    last_emit = [time.monotonic()]

    async def producer() -> None:
        try:
            async for name, payload in events:
                if stop.is_set():
                    break
                last_emit[0] = time.monotonic()
                await queue.put(("event", encode_event(str(name), payload)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("SSE 生产协程异常")
            await queue.put(
                ("event", encode_event("error", {"message": f"{type(exc).__name__}: {exc}"}))
            )
        finally:
            await queue.put(_DONE)

    async def heartbeat() -> None:
        try:
            while not stop.is_set():
                await asyncio.sleep(poll_s)
                if stop.is_set():
                    return
                if await _is_disconnected(request):
                    logger.info("客户端已断开，结束 SSE 流")
                    stop.set()
                    await queue.put(_DONE)
                    return
                if time.monotonic() - last_emit[0] >= heartbeat_s:
                    last_emit[0] = time.monotonic()
                    await queue.put(("ping", encode_ping()))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("SSE 心跳协程异常")

    tasks = [asyncio.create_task(producer()), asyncio.create_task(heartbeat())]
    try:
        while True:
            kind, frame = await queue.get()
            if kind == "__done__":
                break
            if frame:
                yield frame
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def sse_response(
    events: AsyncIterator[tuple[str, Any]],
    request: Request | None = None,
    *,
    heartbeat_s: float = HEARTBEAT_S,
) -> StreamingResponse:
    """把事件流包成标准的 text/event-stream 响应。

    `X-Accel-Buffering: no` 是给 nginx 一类反代看的：不关掉它会整段缓冲，
    前端就只能等流结束才看到字。
    """
    return StreamingResponse(
        heartbeat_wrap(events, request, heartbeat_s=heartbeat_s),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
