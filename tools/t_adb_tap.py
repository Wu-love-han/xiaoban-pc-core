"""手机 ADB 工具：点击手机屏幕坐标"""

from __future__ import annotations

from tools import _adb_common as A

def _run(args, ctx):
    x, y = int(args.get("x", 0)), int(args.get("y", 0))
    if x < 0 or y < 0:
        return {"ok": False, "output": "坐标不能为负"}
    rc, out, err = A.shell(f"input tap {x} {y}")
    return {"ok": rc == 0, "output": f"点击 ({x},{y})" if rc == 0 else (err or "点击失败")}


TOOL = {
    "name": "phone.tap",
    "title": "点击屏幕",
    "desc": "点击手机屏幕坐标",
    "danger": False,
    "params": {'type': 'object', 'properties': {'x': {'type': 'integer'}, 'y': {'type': 'integer'}}, 'required': ['x', 'y']},
    "run": _run,
}
