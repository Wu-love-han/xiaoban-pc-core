"""phone.input_text：往手机输入框写文字。

优先走 App 的无障碍 ACTION_SET_TEXT（直接写进控件，中文也没问题，毫秒级）；
App 不在才回落 adb shell input text（只支持 ASCII，中文会丢）。
"""

from __future__ import annotations

from tools import _adb_common as A


def _run(args, ctx):
    text = str(args.get("text") or "")
    if not text:
        return {"ok": False, "output": "文字为空"}
    if A.danger(text):
        return {"ok": False, "output": "内容命中危险黑名单（支付/密码/验证码等），已拒绝"}

    # 快路径：App 的无障碍 SET_TEXT（支持中文）
    if A.app_ready():
        ok, msg = A.app_type(text)
        if ok:
            return {"ok": True, "output": msg, "data": {"via": "accessibility"}}

    # 慢路径：adb input text（只支持 ASCII）
    esc = text.replace(" ", "%s").replace("'", "\\'")
    rc, out, err = A.shell(f"input text '{esc}'")
    if rc != 0:
        return {"ok": False, "output": err or "输入失败"}
    return {"ok": True, "output": "已输入（adb 通道，中文可能不支持）", "data": {"via": "adb"}}


TOOL = {
    "name": "phone.input_text",
    "title": "手机输入文字",
    "desc": "往手机当前输入框写文字。走无障碍直接写入控件，中文也支持；输入前先用 phone.click_text 点一下输入框。",
    "danger": False,
    "params": {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']},
    "run": _run,
}
