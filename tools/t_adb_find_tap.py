"""按文字找元素并点击（不用截图、不用算坐标）。"""

from __future__ import annotations

from tools import _adb_common as A


def _run(args, ctx):
    kw = str(args.get("keyword") or "").strip()
    if not kw:
        return {"ok": False, "output": "要给我一个关键词（界面上显示的文字）"}
    if A.danger(kw):
        return {"ok": False, "output": "关键词命中危险黑名单，已拒绝"}
    el = A.find_element(kw)
    if not el:
        return {"ok": False, "output": f"界面上没找到「{kw}」。可以先调 phone.ui_tree 看看有什么"}
    x, y = el["center"]
    rc, out, err = A.shell(f"input tap {x} {y}")
    label = el["text"] or el["desc"] or el["id"]
    return {
        "ok": rc == 0,
        "output": f"已点击「{label}」@({x},{y})" if rc == 0 else (err or "点击失败"),
        "data": {"element": el},
    }


TOOL = {
    "name": "phone.find_tap",
    "title": "按文字点击",
    "desc": "在界面上找含指定文字的按钮/条目并点它（不用截图）",
    "danger": False,
    "params": {"type": "object", "properties": {"keyword": {"type": "string", "description": "界面上的文字，如「发送」「设置」"}}, "required": ["keyword"]},
    "run": _run,
}
