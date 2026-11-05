"""agent.inbox：看别的 AI 发来的消息。"""

from __future__ import annotations

from typing import Any

from . import _common as C

SELF_ID = "pc"


def run(args: dict, ctx: Any) -> dict:
    action = str(args.get("action") or "list").strip().lower()

    try:
        from core import agents  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"读不到 AI 通信模块：{exc}", "InitFailed")

    if action == "state":
        try:
            st = agents.state()
        except Exception as exc:  # noqa: BLE001
            return C.fail(str(exc), "StateFailed")
        lines = []
        for aid, info in st["roster"].items():
            n = st["unread"].get(aid, 0)
            lines.append(f"  {info['name']}（{aid}）{info['role']}：{info['desc']}"
                         + (f"  [{n} 条未读]" if n else ""))
        return C.ok("三个 AI：\n" + "\n".join(lines), state=st)

    try:
        limit = int(args.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    unread_only = bool(args.get("unread_only", True))

    try:
        items = agents.inbox(SELF_ID, limit=limit, unread_only=unread_only)
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"读收件箱失败：{exc}", "InboxFailed")

    if not items:
        return C.ok("没有新消息。", items=[])

    lines = []
    for m in items:
        lines.append(f"  [{m['from_name']}] {m['content'][:120]}")
    if bool(args.get("mark_read", True)):
        try:
            agents.mark_read(SELF_ID)
        except Exception:  # noqa: BLE001
            pass
    return C.ok(f"{len(items)} 条消息：\n" + "\n".join(lines), items=items)


TOOL = {
    "name": "agent.inbox",
    "title": "看别的 AI 发来的消息",
    "desc": "查小随（手机）和小动（机器人）发给你的消息。action=state 看三个 AI 是谁。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "state"], "description": "list=看消息（默认），state=看三个 AI 的身份"},
            "limit": {"type": "integer", "description": "最多几条"},
            "unread_only": {"type": "boolean", "description": "只看未读（默认 true）"},
            "mark_read": {"type": "boolean", "description": "看完标记已读（默认 true）"},
        },
    },
    "run": C.guard(run),
}
