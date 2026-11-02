"""手机 ADB 工具：截取手机当前屏幕（只读，返回图片保存路径）"""

from __future__ import annotations

from tools import _adb_common as A

def _run(args, ctx):
    ok, msg = A.device_ready()
    if not ok:
        return {"ok": False, "output": msg}
    ok, data = A.screenshot_bytes()
    if not ok:
        return {"ok": False, "output": str(data)}
    out = ctx.workspace / "phone_screenshot.png"
    out.write_bytes(data)
    return {"ok": True, "output": f"已截图：{out}（{len(data)} 字节）", "data": {"path": str(out)}}


TOOL = {
    "name": "phone.screenshot",
    "title": "手机截图",
    "desc": "截取手机当前屏幕（只读，返回图片保存路径）",
    "danger": False,
    "params": {'type': 'object', 'properties': {}},
    "run": _run,
}
