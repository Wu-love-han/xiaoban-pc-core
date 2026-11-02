"""手机 ADB 工具：读取手机通知栏（只读）"""

from __future__ import annotations

from tools import _adb_common as A

def _run(args, ctx):
    rc, out, err = A.shell("dumpsys notification --noredact | grep -E 'android.title|android.text' | head -20")
    if rc != 0:
        return {"ok": False, "output": err or "读通知失败"}
    lines = [l.strip() for l in out.splitlines() if l.strip()][:20]
    return {"ok": True, "output": "\n".join(lines) if lines else "没有通知"}


TOOL = {
    "name": "phone.notifications",
    "title": "读通知",
    "desc": "读取手机通知栏（只读）",
    "danger": False,
    "params": {'type': 'object', 'properties': {}},
    "run": _run,
}
