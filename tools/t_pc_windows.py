"""pc.windows：列出当前打开的窗口。"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _desktop_common as D


def run(args: dict, ctx: Any) -> dict:
    try:
        wins = D.list_windows()
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"列窗口失败：{exc}", f"{type(exc).__name__}")

    kw = str(args.get("keyword") or "").strip().lower()
    if kw:
        wins = [w for w in wins if kw in w["title"].lower()]

    if not wins:
        return C.ok("现在没有匹配的窗口开着。", items=[], count=0)

    lines = [f"{i}. {w['title']}" for i, w in enumerate(wins[:20])]
    return C.ok(
        f"开着 {len(wins)} 个窗口：\n" + "\n".join(lines),
        items=wins[:20], count=len(wins), foreground=D.foreground_title(),
    )


TOOL = {
    "name": "pc.windows",
    "title": "看有哪些窗口",
    "desc": "列出电脑上当前打开的程序窗口（标题）。想知道某个程序开没开、窗口叫什么时用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {"keyword": {"type": "string", "description": "只看标题含这个词的窗口（可省略）"}},
    },
    "run": C.guard(run),
}
