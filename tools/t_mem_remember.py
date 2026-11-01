"""mem.remember：记住一条（key → value）。

直接复用 core.db.remember()，不在这里写 SQL——契约要求数据访问只有一处。

一个刻意的宽松设计：模型经常只给一句「用户喜欢喝美式」而不给 key。
这种情况下不报错，而是从这句话里截一个短 key，保证「记住」这件事永远能成。
因为拒绝记一条记忆，比记下一个 key 稍微丑一点的记忆要糟得多。
"""

from __future__ import annotations

import re
from typing import Any

from . import _common as C

_KEY_MAX = 40
_VALUE_MAX = 500


def _derive_key(value: str) -> str:
    """没给 key 时从内容里造一个：取第一句，去掉标点，压到 40 字。"""
    first = re.split(r"[。！？!?\n；;，,]", value.strip(), maxsplit=1)[0].strip()
    first = re.sub(r"^我(喜欢|讨厌|习惯|是|叫|住在|在)", r"\1", first).strip()
    key = first or value.strip()
    return key[:_KEY_MAX]


def run(args: dict, ctx: Any) -> dict:
    if not bool(C.cfg_get(ctx, "memory.enabled", True)):
        return C.fail("配置里把记忆功能关掉了（memory.enabled = false）。", "MemoryDisabled")

    value = args.get("value")
    if value is None:
        value = args.get("content") or args.get("text")
    value = "" if value is None else str(value).strip()
    if not value:
        return C.fail("要记什么呢？value 是空的。", "MissingArg: value")

    key = str(args.get("key") or "").strip()
    if not key:
        key = _derive_key(value)
    key = key[:_KEY_MAX]
    value = value[:_VALUE_MAX]

    scope = str(args.get("scope") or "global").strip() or "global"

    try:
        C.ensure_db()
        from core import db

        res = db.remember(key, value, scope=scope)
    except Exception as exc:  # noqa: BLE001
        return C.fail(
            f"这条我记到一半出错了（{type(exc).__name__}），可能数据库没准备好。",
            f"{type(exc).__name__}: {exc}",
        )

    if res.get("updated"):
        out = f"记下了（原来就有「{key}」，我更新成了新的）：{value}"
    else:
        out = f"记下了：{key} → {value}"

    return C.ok(out, key=key, value=value, scope=scope, updated=bool(res.get("updated")))


TOOL = {
    "name": "mem.remember",
    "title": "记住一件事",
    "desc": "把一条信息长期记住，以后还能想起来。适合记用户的偏好、习惯、称呼、重要事实。key 是短标签（可省略，会自动从内容里取）。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "短标签，比如「咖啡口味」「生日」；省略则自动从 value 里取",
            },
            "value": {"type": "string", "description": "要记住的内容"},
            "scope": {
                "type": "string",
                "description": "作用域，默认 global（全局）",
            },
        },
        "required": ["value"],
    },
    "run": C.guard(run),
}
