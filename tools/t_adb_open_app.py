"""phone.open_app：打开手机上的应用。

优先走 App 的本地服务（远程/无 USB 也能用），App 不在才回落 adb monkey。
"""

from __future__ import annotations

from tools import _adb_common as A


def _run(args, ctx):
    pkg = str(args.get("package") or "").strip()
    if not pkg:
        return {"ok": False, "output": "包名不能为空"}
    if A.danger(pkg):
        return {"ok": False, "output": "这个包名命中危险黑名单，已拒绝"}

    # 快路径：App 的 /open_app（远程可用）
    if A.app_ready():
        ok, msg = A.app_open_app(pkg)
        if ok:
            return {"ok": True, "output": msg, "data": {"via": "app"}}

    # 慢路径：adb monkey（需要 USB 或无线调试）
    rc, out, err = A.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
    if rc != 0:
        return {"ok": False, "output": err or "打开失败（App 没连上，adb 也不可用）"}
    return {"ok": True, "output": f"打开了 {pkg}", "data": {"via": "adb"}}


TOOL = {
    "name": "phone.open_app",
    "title": "打开手机应用",
    "desc": "按包名打开手机上的应用。走 App 本地服务，远程（不在同一 WiFi、没插 USB）也能用。",
    "danger": False,
    "params": {"type": "object", "properties": {"package": {"type": "string", "description": "应用包名，如 com.tencent.mm（微信）"}}, "required": ["package"]},
    "run": _run,
}
