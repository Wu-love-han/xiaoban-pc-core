"""mem.update：改一条记忆，或者遗忘它。

小伴的需求：「记住的东西要能更新和遗忘，别只增不减」
- action=update 改内容/分类/重要度
- action=forget 删掉（真的删）
- action=decay  批量给很久没想起的记忆降权（不硬删）
"""

from __future__ import annotations

from typing import Any

from . import _common as C


def run(args: dict, ctx: Any) -> dict:
    action = str(args.get("action") or "update").strip().lower()

    if action == "decay":
        try:
            from core import memory_engine  # noqa: PLC0415

            memory_engine.init()
            n = memory_engine.decay_long_term(
                older_than_days=int(args.get("days") or 60),
                min_importance=float(args.get("min_importance") or 0.3),
            )
        except Exception as exc:  # noqa: BLE001
            return C.fail(f"降权失败：{exc}", f"{type(exc).__name__}")
        return C.ok(f"给 {n} 条很久没想起的记忆降了权（没删，只是不再优先跳出来）。", affected=n)

    try:
        mid = int(args.get("id"))
    except (TypeError, ValueError):
        return C.fail("要给我记忆的 id（先用 mem.recall 查到 id）。", "MissingArg: id")

    try:
        from core import memory_engine  # noqa: PLC0415

        memory_engine.init()
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"记忆库打不开：{exc}", f"{type(exc).__name__}")

    if action == "forget":
        ok = memory_engine.forget_long_term(mid)
        if not ok:
            return C.fail(f"没找到 id={mid} 的记忆。", "NotFound")
        return C.ok(f"忘掉 #{mid} 了。", id=mid, action="forget")

    # update
    ok = memory_engine.update_long_term(
        mid,
        content=str(args.get("content") or ""),
        category=str(args.get("category") or ""),
        importance=args.get("importance"),
    )
    if not ok:
        return C.fail(f"没改成功：id={mid} 不存在，或者没给要改的字段。", "NotFound")
    return C.ok(f"改好 #{mid} 了。", id=mid, action="update")


TOOL = {
    "name": "mem.update",
    "title": "改记忆 / 遗忘",
    "desc": (
        "修改或删除一条长期记忆。action=update 改内容/分类/重要度；"
        "action=forget 删掉；action=decay 批量给很久没想起的记忆降权。"
        "先用 mem.recall 查到 id。"
    ),
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["update", "forget", "decay"]},
            "id": {"type": "integer", "description": "记忆 id（mem.recall 返回的）"},
            "content": {"type": "string", "description": "新的内容"},
            "category": {"type": "string", "description": "新的分类/场景"},
            "importance": {"type": "number", "description": "新的重要度 0-1"},
            "days": {"type": "integer", "description": "decay 时：多少天没想起就降权，默认 60"},
        },
        "required": ["action"],
    },
    "run": C.guard(run),
}
