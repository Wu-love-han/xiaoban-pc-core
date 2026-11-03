"""pc.hotkey：按快捷键，如 enter / ctrl+v / alt+f4。"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _desktop_common as D


def run(args: dict, ctx: Any) -> dict:
    combo = str(args.get("keys") or args.get("combo") or "").strip()
    if not combo:
        return C.fail("要按什么键？比如 enter、ctrl+v、alt+tab。", "MissingArg: keys")

    # 底线：不替用户按"确认支付"这类（无法判断语义，只拦明显危险组合）
    low = combo.lower().replace(" ", "")
    if low in ("alt+f4",) and bool(args.get("confirm_close")):
        pass  # 允许，但需要显式确认

    if not D.press_keys(combo):
        return C.fail(f"认不出这个按键组合：{combo}", "BadKey")

    return C.ok(f"按了 {combo}", keys=combo, foreground=D.foreground_title())


TOOL = {
    "name": "pc.hotkey",
    "title": "按快捷键",
    "desc": "按下键盘组合键，如 enter、tab、esc、ctrl+v、ctrl+a、alt+tab、win+d。填完表单按回车、复制粘贴时用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {"keys": {"type": "string", "description": "组合键，如 enter / ctrl+v / alt+tab"}},
        "required": ["keys"],
    },
    "run": C.guard(run),
}
