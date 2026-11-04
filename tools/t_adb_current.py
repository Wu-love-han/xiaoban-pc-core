"""phone.current_app：看手机当前前台是什么应用。

优先走 App 的 /foreground（远程可用），App 不在才回落 adb dumpsys。
"""

from __future__ import annotations

from tools import _adb_common as A


def _run(args, ctx):
    # 快路径：App
    if A.app_ready():
        ok, pkg = A.app_foreground()
        if ok:
            return {"ok": True, "output": f"当前前台：{pkg or '(拿不到)'}", "data": {"package": pkg, "via": "app"}}

    # 慢路径：adb
    rc, out, err = A.shell("dumpsys window | grep mCurrentFocus")
    if rc != 0:
        return {"ok": False, "output": err or "拿不到当前应用（App 没连上，adb 也不可用）"}
    return {"ok": True, "output": out.strip()[:300], "data": {"via": "adb"}}


TOOL = {
    "name": "phone.current_app",
    "title": "手机当前应用",
    "desc": "看手机现在前台是哪个应用。走 App 本地服务，远程也能用。",
    "danger": False,
    "params": {"type": "object", "properties": {}},
    "run": _run,
}
