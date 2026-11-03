"""pc.screen：截电脑屏幕，存成图片给模型看。"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _desktop_common as D


def run(args: dict, ctx: Any) -> dict:
    import time
    from pathlib import Path

    ws = Path(getattr(ctx, "workspace", None) or ".")
    ws.mkdir(parents=True, exist_ok=True)
    name = f"screen_{int(time.time())}.png"
    path = ws / name
    try:
        w, h = D.screenshot(str(path))
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"截图失败：{exc}", f"{type(exc).__name__}")
    return C.ok(
        f"截好了，{w}x{h}，存在 {path}",
        path=str(path), width=w, height=h,
        screen=D.screen_size(), scale=D.screen_scale(),
        foreground=D.foreground_title(),
    )


TOOL = {
    "name": "pc.screen",
    "title": "截电脑屏幕",
    "desc": "截取电脑当前屏幕存成图片。想知道界面上有什么、按钮在哪、某步操作有没有成功时用。",
    "danger": False,
    "params": {"type": "object", "properties": {}},
    "run": C.guard(run),
}
