"""手机 ADB 工具：在手机输入框输入文字"""

from __future__ import annotations

from tools import _adb_common as A

def _run(args, ctx):
    text = str(args.get("text") or "")
    if not text:
        return {"ok": False, "output": "文字为空"}
    if A.danger(text):
        return {"ok": False, "output": "内容命中危险黑名单（支付/密码/验证码等），已拒绝"}
    esc = text.replace(" ", "%s").replace("'", "\\'")
    rc, out, err = A.shell(f"input text '{esc}'")
    return {"ok": rc == 0, "output": "已输入" if rc == 0 else (err or "输入失败")}


TOOL = {
    "name": "phone.input_text",
    "title": "手机输入文字",
    "desc": "在手机输入框输入文字",
    "danger": False,
    "params": {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']},
    "run": _run,
}
