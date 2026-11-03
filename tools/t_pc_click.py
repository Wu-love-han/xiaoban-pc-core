"""pc.click：在屏幕坐标点一下鼠标。"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _desktop_common as D


def run(args: dict, ctx: Any) -> dict:
    try:
        x = int(args.get("x"))
        y = int(args.get("y"))
    except (TypeError, ValueError):
        return C.fail("要给我 x、y 坐标（先用 pc.screen 截图看位置）。", "MissingArg: x/y")

    # 坐标按「截图里的像素」理解，内部会自动换算成鼠标坐标
    from PIL import ImageGrab  # noqa: PLC0415
    try:
        img = ImageGrab.grab(all_screens=True)
        sw, sh = img.size
    except Exception:  # noqa: BLE001
        sw, sh = D.screen_size()
    if not (0 <= x < sw and 0 <= y < sh):
        return C.fail(f"坐标 ({x},{y}) 超出屏幕范围（截图是 {sw}x{sh}）。", "OutOfRange")

    # 底线：支付/收银台界面一律不点
    if D.looks_like_payment():
        return C.fail(
            f"当前窗口「{D.foreground_title()}」看起来是支付/收银台页面，我不在这里点击。",
            "Blocked:Payment",
        )

    button = str(args.get("button") or "left").lower()
    if button not in ("left", "right"):
        button = "left"
    double = bool(args.get("double"))

    try:
        D.click(x, y, button, double)
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"点击失败：{exc}", f"{type(exc).__name__}")

    what = "双击" if double else ("右键" if button == "right" else "点击")
    lx, ly = D.to_logical(x, y)
    return C.ok(
        f"在 ({x},{y}) {what}了（实际鼠标位置 {lx},{ly}）",
        x=x, y=y, logical=[lx, ly], foreground=D.foreground_title(),
    )


TOOL = {
    "name": "pc.click",
    "title": "点鼠标",
    "desc": "在电脑屏幕的指定坐标点一下（或双击/右键）。配合 pc.screen 截图找位置用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "横坐标（像素）"},
            "y": {"type": "integer", "description": "纵坐标（像素）"},
            "button": {"type": "string", "enum": ["left", "right"], "description": "左键还是右键，默认左键"},
            "double": {"type": "boolean", "description": "true = 双击"},
        },
        "required": ["x", "y"],
    },
    "run": C.guard(run),
}
