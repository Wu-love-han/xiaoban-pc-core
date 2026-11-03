"""pc.github_search：搜 GitHub 上的插件/仓库。

用户需求：「我要在搜索 GitHub 插件，打开链接查看具体详情，下载下来，这个软件 ai 能直接识别和使用」
"""

from __future__ import annotations

from typing import Any

from . import _common as C


def run(args: dict, ctx: Any) -> dict:
    q = str(args.get("query") or args.get("q") or "").strip()
    try:
        limit = int(args.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(30, limit))

    try:
        from core import github_api  # noqa: PLC0415

        res = github_api.search_plugins(q, limit=limit) if not bool(args.get("general")) else github_api.search(q, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"搜索失败：{exc}", f"{type(exc).__name__}")

    if not res.get("ok"):
        return C.fail(f"搜索失败：{res.get('error')}", "SearchFailed")

    items = res.get("items") or []
    if not items:
        return C.ok(f"没搜到「{q}」相关的仓库。换个关键词试试。", items=[], query=q)

    lines = []
    for it in items:
        lines.append(
            f"- {it['fullName']}  ⭐{it['stars']}  {it.get('language') or ''}\n"
            f"  {it.get('description') or '(没有描述)'}\n"
            f"  链接：https://github.com/{it['fullName']}"
        )
    return C.ok(
        f"搜到 {len(items)} 个（关键词「{q}」）：\n" + "\n".join(lines),
        items=items, query=q, count=len(items),
    )


TOOL = {
    "name": "pc.github_search",
    "title": "搜 GitHub 插件",
    "desc": "在 GitHub 上搜插件/仓库。返回仓库名、星数、描述和链接。想装什么功能先搜一下，搜到合适的用 pc.github_install 装。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "关键词，如 memory / voice / esp32"},
            "limit": {"type": "integer", "description": "返回几条（1-30），默认 10"},
            "general": {"type": "boolean", "description": "true = 不限定插件生态，搜全站"},
        },
        "required": ["query"],
    },
    "run": C.guard(run),
}
