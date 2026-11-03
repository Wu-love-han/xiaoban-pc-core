"""pc.focus_window：把某个窗口切到前台。"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _desktop_common as D


def run(args: dict, ctx: Any) -> dict:
    kw = str(args.get("title") or args.get("keyword") or "").strip()
    if not kw:
        return C.fail("要切到哪个窗口？给我窗口标题里的几个字。", "MissingArg: title")
    w = D.find_window(kw)
    if not w:
        wins = D.list_windows()
        names = "、".join(x["title"][:20] for x in wins[:6])
        return C.fail(f"没找到标题含「{kw}」的窗口。现在开着的是：{names}", "NotFound")
    if not D.focus_window(w["hwnd"]):
        return C.fail(f"找到了「{w['title']}」但切不过去（可能被系统拦了）", "FocusFailed")
    return C.ok(f"已经切到「{w['title']}」", window=w)


TOOL = {
    "name": "pc.focus_window",
    "title": "切到某个窗口",
    "desc": "把标题含指定文字的窗口带到前台，方便接下来点它或往里打字。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {"title": {"type": "string", "description": "窗口标题里的几个字，如 WorkBuddy"}},
        "required": ["title"],
    },
    "run": C.guard(run),
}
