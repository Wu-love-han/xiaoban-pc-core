"""mem.recall：按关键词召回记忆。

直接复用 core.db.recall()（关键词 + 权重排序，不做向量检索）。

一个判断：召回是「有就更好，没有也不算错」。查不到东西时返回 ok:True +
「没印象」比返回 ok:False 更合适——模型不该因为「想不起来」就认为自己出错了。
"""

from __future__ import annotations

from typing import Any

from . import _common as C


def run(args: dict, ctx: Any) -> dict:
    if not bool(C.cfg_get(ctx, "memory.enabled", True)):
        return C.fail("配置里把记忆功能关掉了（memory.enabled = false）。", "MemoryDisabled")

    query = str(args.get("query") or args.get("key") or args.get("q") or "").strip()
    scope = str(args.get("scope") or "global").strip() or "global"

    default_limit = int(C.cfg_get(ctx, "memory.max_inject", 6) or 6)
    try:
        limit = int(args.get("limit") or default_limit)
    except (TypeError, ValueError):
        limit = default_limit
    limit = max(1, min(limit, 20))

    try:
        C.ensure_db()
        from core import db

        rows = db.recall(query, scope=scope, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return C.fail(
            f"翻记忆的时候出错了（{type(exc).__name__}），可能数据库没准备好。",
            f"{type(exc).__name__}: {exc}",
        )

    items = [
        {
            "key": str(r.get("key") or ""),
            "value": str(r.get("value") or ""),
            "scope": str(r.get("scope") or ""),
            "weight": round(float(r.get("weight") or 0), 2),
        }
        for r in rows
    ]

    if not items:
        what = f"「{query}」" if query else "相关的事"
        return C.ok(f"关于{what}我这儿没记着什么。", query=query, items=[])

    lines = [f"- {it['key']}：{it['value']}" for it in items]
    head = f"想起 {len(items)} 条" + (f"关于「{query}」的" if query else "")
    return C.ok(f"{head}：\n" + "\n".join(lines), query=query, items=items)


TOOL = {
    "name": "mem.recall",
    "title": "想起一件事",
    "desc": "按关键词翻长期记忆，看以前记过什么。给关键词就按相关性找，不给就把记得最清楚的几条列出来。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "关键词；省略则按权重列出最近/最重要的几条",
            },
            "limit": {"type": "integer", "description": "最多几条（1-20）"},
            "scope": {"type": "string", "description": "作用域，默认 global"},
        },
        "required": [],
    },
    "run": C.guard(run),
}
