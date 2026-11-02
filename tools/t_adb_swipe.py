"""手机 ADB 工具：在手机上滑动"""

from __future__ import annotations

from tools import _adb_common as A

def _run(args, ctx):
    x1,y1,x2,y2 = (int(args.get(k,0)) for k in ("x1","y1","x2","y2"))
    ms = int(args.get("ms", 300))
    rc, out, err = A.shell(f"input swipe {x1} {y1} {x2} {y2} {ms}")
    return {"ok": rc == 0, "output": f"滑动 ({x1},{y1})→({x2},{y2})" if rc == 0 else (err or "滑动失败")}


TOOL = {
    "name": "phone.swipe",
    "title": "滑动屏幕",
    "desc": "在手机上滑动",
    "danger": False,
    "params": {'type': 'object', 'properties': {'x1': {'type': 'integer'}, 'y1': {'type': 'integer'}, 'x2': {'type': 'integer'}, 'y2': {'type': 'integer'}, 'ms': {'type': 'integer'}}, 'required': ['x1', 'y1', 'x2', 'y2']},
    "run": _run,
}
