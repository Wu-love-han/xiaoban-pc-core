"""agent.send：给另一个 AI 发消息。

三个 AI 共同扮演「小伴」这一个陪伴角色：
  小伴（PC）  —— 大脑
  小随（手机）—— 手
  小动（机器人）—— 身体

它们通过 PC 中转互相联系。
"""

from __future__ import annotations

from typing import Any

from . import _common as C

SELF_ID = "pc"   # 这个工具跑在 PC 上，所以发送方是 pc


def run(args: dict, ctx: Any) -> dict:
    to_id = str(args.get("to") or "").strip().lower()
    content = str(args.get("content") or "").strip()
    kind = str(args.get("kind") or "note").strip()

    if not to_id:
        return C.fail("要发给谁？phone（小随）还是 robot（小动）？", "MissingArg: to")
    if not content:
        return C.fail("要说什么？", "MissingArg: content")

    try:
        from core import agents  # noqa: PLC0415

        r = agents.send(SELF_ID, to_id, content, kind=kind)
    except ValueError as exc:
        return C.fail(str(exc), "BadTarget")
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"发送失败：{exc}", "SendFailed")

    name = agents.who(to_id)["name"]
    return C.ok(
        f"发给{name}了：{content[:60]}{'…' if len(content) > 60 else ''}\n"
        f"（他下次心跳时会收到）",
        id=r["id"], to=to_id,
    )


TOOL = {
    "name": "agent.send",
    "title": "给另一个 AI 发消息",
    "desc": (
        "给另外两个 AI 之一发消息。to=phone 是小随（手机），to=robot 是小动（机器人）。"
        "用来协调任务、同步进度、商量怎么办。别发废话。"
    ),
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "enum": ["phone", "robot"], "description": "发给谁"},
            "content": {"type": "string", "description": "内容"},
            "kind": {"type": "string", "description": "类型：note/ask/report/task"},
        },
        "required": ["to", "content"],
    },
    "run": C.guard(run),
}
