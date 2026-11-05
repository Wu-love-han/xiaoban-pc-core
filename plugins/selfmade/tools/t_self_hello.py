"""self.hello：报个到。"""
from __future__ import annotations
from typing import Any
from tools import _common as C


def run(args: dict, ctx: Any) -> dict:
    who = str(args.get("who") or "世界").strip()
    return C.ok(f"我是自造工具，{who} 你好")


TOOL = {
    "name": "self.hello",
    "title": "自造测试",
    "desc": "跟谁打招呼",
    "danger": False,
    "params": {"type": "object", "properties": {"who": {"type": "string"}}},
    "run": C.guard(run),
}
