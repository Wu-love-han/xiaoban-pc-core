"""phone.click_text：按文字点手机界面（走 App 无障碍，毫秒级）。"""

from __future__ import annotations

from typing import Any

from . import _adb_common as A
from . import _common as C


def run(args: dict, ctx: Any) -> dict:
    kw = str(args.get("text") or args.get("keyword") or "").strip()
    if not kw:
        return C.fail("要给我界面上显示的文字，比如「发送」「设置」。", "MissingArg: text")
    if A.danger(kw):
        return C.fail("这个词命中危险黑名单，已拒绝。", "Blocked:Danger")

    # 优先走 App（直接 performAction，不用坐标）
    if A.app_ready():
        ok, msg = A.app_click_text(kw)
        if ok:
            return C.ok(msg, via="app")
        # App 点了但没找到 → 回落按坐标点
        el = A.find_element(kw)
        if el:
            x, y = el["center"]
            rc, out, err = A.shell(f"input tap {x} {y}")
            if rc == 0:
                return C.ok(f"按坐标点了「{kw}」@({x},{y})", via="coords")
        return C.fail(f"{msg}。可以先 phone.ui_tree 看看界面上有什么", "NotFound")

    # App 不在 → 老路：结构树找元素再点坐标
    el = A.find_element(kw)
    if not el:
        return C.fail(f"界面上没找到「{kw}」。先 phone.ui_tree 看看有什么", "NotFound")
    x, y = el["center"]
    rc, out, err = A.shell(f"input tap {x} {y}")
    if rc != 0:
        return C.fail(err or "点击失败", "TapFailed")
    return C.ok(f"点了「{el['text'] or el['desc'] or el['id']}」@({x},{y})", via="coords", element=el)


TOOL = {
    "name": "phone.click_text",
    "title": "按文字点手机",
    "desc": "在手机界面上找含指定文字的按钮并点击。走无障碍直接点节点，比截图快很多。找不到时会提示先看界面结构。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "界面上的文字，如「发送」「设置」「允许」"}},
        "required": ["text"],
    },
    "run": C.guard(run),
}
