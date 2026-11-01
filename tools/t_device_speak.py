"""device.speak：让机器人说一句话（走设备队列）。

注意这不是 TTS 播报，而是把话交给设备端（机器人本体）去说。
所以工具只负责「把话放进队列」，不负责「念出来」——真后端在设备那边。

模拟模式下句子真的进进程内存的队列，device.speak 连说两句，队列里就有两条，
以后要给设备端做轮询接口可以直接接这个队列。
"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _devices as D

MAX_SPEAK = 200


def run(args: dict, ctx: Any) -> dict:
    text = args.get("text")
    if text is None:
        text = args.get("content") or args.get("say") or args.get("message")
    text = "" if text is None else str(text).strip()

    if not text:
        return C.fail("要让它说什么呢？text 是空的。", "MissingArg: text")

    if len(text) > MAX_SPEAK:
        text = text[:MAX_SPEAK]

    if D.simulate_on(ctx):
        depth = D.push_speech(text)
        return C.ok(
            f"把「{text}」交给机器人了（模拟队列里现在 {depth} 条）。",
            text=text,
            queued=depth,
            simulated=True,
        )

    ok, data = D.backend_speak(ctx, text)
    if not ok:
        return C.fail(f"话没送出去：{data}", "DeviceBackendUnavailable")
    return C.ok(f"「{text}」已经发给设备端了。", text=text, raw=data)


TOOL = {
    "name": "device.speak",
    "title": "让它说句话",
    "desc": "把一句话交给机器人本体去说（进设备队列，不是本机喇叭播放）。要主动开口提醒、播报事情时用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要说的话，最多 200 字"}
        },
        "required": ["text"],
    },
    "run": C.guard(run),
}
