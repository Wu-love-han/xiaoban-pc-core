"""手机 ADB 工具：按 HOME/BACK/ENTER 等键"""

from __future__ import annotations

from tools import _adb_common as A

_KEYS = {"HOME":"KEYCODE_HOME","BACK":"KEYCODE_BACK","ENTER":"KEYCODE_ENTER",
         "MENU":"KEYCODE_MENU","POWER":"KEYCODE_POWER","VOLUP":"KEYCODE_VOLUME_UP",
         "VOLDOWN":"KEYCODE_VOLUME_DOWN","RECENTS":"KEYCODE_APP_SWITCH"}


def _run(args, ctx):
    k = str(args.get("key") or "").upper().strip()
    code = _KEYS.get(k)
    if not code:
        return {"ok": False, "output": f"不支持的按键：{k}（可用：{', '.join(_KEYS)}）"}
    rc, out, err = A.shell(f"input keyevent {code}")
    return {"ok": rc == 0, "output": f"按键 {k}" if rc == 0 else (err or "按键失败")}


TOOL = {
    "name": "phone.key",
    "title": "手机按键",
    "desc": "按 HOME/BACK/ENTER 等键",
    "danger": False,
    "params": {'type': 'object', 'properties': {'key': {'type': 'string', 'description': 'HOME/BACK/ENTER/...'}}, 'required': ['key']},
    "run": _run,
}
