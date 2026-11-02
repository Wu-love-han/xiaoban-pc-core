"""手机 ADB 工具：查看手机当前前台应用（只读）"""

from __future__ import annotations

from tools import _adb_common as A

def _run(args, ctx):
    rc, out, err = A.shell("dumpsys window | grep mCurrentFocus")
    if rc != 0 or not out.strip():
        return {"ok": False, "output": err or "读不到前台应用"}
    return {"ok": True, "output": out.strip()[:300]}


TOOL = {
    "name": "phone.current_app",
    "title": "当前应用",
    "desc": "查看手机当前前台应用（只读）",
    "danger": False,
    "params": {'type': 'object', 'properties': {}},
    "run": _run,
}
