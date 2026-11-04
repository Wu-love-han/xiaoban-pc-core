"""pc.click_text：按元素名字点击（Windows UIAutomation）。

为什么需要：
  pc.look 只给文字描述，模型得猜坐标，猜错就点不到（AI 卡了十几轮）。
  这个工具直接用元素名字找，拿到精确坐标再点。
"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _desktop_common as D
from . import t_pc_ui as UI


def run(args: dict, ctx: Any) -> dict:
    kw = str(args.get("text") or args.get("name") or "").strip()
    if not kw:
        return C.fail("要给我元素名字，比如「新建会话」「发送」。", "MissingArg: text")
    if D.looks_like_payment():
        return C.fail("当前窗口像支付页面，不在这里点击。", "Blocked:Payment")

    win = str(args.get("window") or "").strip()
    if win:
        w = D.find_window(win)
        if not w:
            names = "、".join(x["title"][:18] for x in D.list_windows()[:6])
            return C.fail(f"没找到标题含「{win}」的窗口。现在开着：{names}", "NotFound")
        D.focus_window(w["hwnd"])
        hwnd = w["hwnd"]
    else:
        hwnd = D.foreground_hwnd()
        if not hwnd:
            return C.fail("拿不到当前窗口", "NoWindow")

    ok, data = UI._run_ps(hwnd, 300)
    if not ok or not data.get("ok"):
        return C.fail(f"读界面失败：{data}", "UIFailed")

    elems = data.get("elements") or []
    low = kw.lower()

    # 先精确匹配，再包含匹配
    exact = [e for e in elems if (e.get("name") or "").strip().lower() == low]
    contains = [e for e in elems if low in (e.get("name") or "").lower()]
    hit = (exact or contains)
    if not hit:
        sample = "、".join((e.get("name") or "")[:12] for e in elems[:10] if e.get("name"))
        return C.fail(f"窗口里没找到含「{kw}」的元素。有这些：{sample}", "NotFound")

    el = hit[0]
    x, y = int(el["x"]), int(el["y"])
    try:
        D.click(x, y)
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"点击失败：{exc}", "ClickFailed")

    label = (el.get("name") or "")[:40]
    more = f"（还有 {len(hit) - 1} 个同名）" if len(hit) > 1 else ""
    return C.ok(
        f"点了「{label}」@({x},{y}){more}",
        element=el, matched=len(hit),
    )


TOOL = {
    "name": "pc.click_text",
    "title": "按名字点元素",
    "desc": (
        "按界面元素的名字点击，不用猜坐标。"
        "比 pc.look 看图估坐标准得多——先 pc.ui 看有什么元素，或直接试。"
        "window 参数指定窗口标题。"
    ),
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "元素名字，如「新建会话」「发送」「关闭」"},
            "window": {"type": "string", "description": "窗口标题里的几个字（省略=前台窗口）"},
        },
        "required": ["text"],
    },
    "run": C.guard(run),
}
