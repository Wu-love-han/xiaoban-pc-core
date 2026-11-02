"""手机 ADB 工具：按包名打开手机应用"""

from __future__ import annotations

from tools import _adb_common as A

def _run(args, ctx):
    pkg = str(args.get("package") or "").strip()
    if not pkg:
        return {"ok": False, "output": "包名不能为空"}
    if A.danger(pkg):
        return {"ok": False, "output": "命中危险黑名单，已拒绝"}
    rc, out, err = A.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
    ok = rc == 0 and "No activities found" not in (out or "")
    return {"ok": ok, "output": f"已打开 {pkg}" if ok else (err or out or "打开失败")}


TOOL = {
    "name": "phone.open_app",
    "title": "手机打开应用",
    "desc": "按包名打开手机应用",
    "danger": False,
    "params": {'type': 'object', 'properties': {'package': {'type': 'string', 'description': '应用包名，如 com.tencent.mm'}}, 'required': ['package']},
    "run": _run,
}
