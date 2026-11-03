"""pc.type：往指定窗口打字（支持中文）。

安全设计（踩过坑）：
- 强烈建议给 window 参数：先切到那个窗口再打字，否则字会打进当前有焦点的任意窗口
- 不给 window 时，返回里带上「打进了哪个窗口」，方便发现打错地方
- 密码/验证码/支付类内容直接拒绝
"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _desktop_common as D


def run(args: dict, ctx: Any) -> dict:
    text = str(args.get("text") or "")
    if not text:
        return C.fail("要输入什么内容呢？", "MissingArg: text")
    if len(text) > 2000:
        return C.fail("一次最多输 2000 字，分几次来吧。", "TooLong")

    # 底线：不替用户输密码 / 验证码 / 银行卡
    if D.looks_secret(text):
        return C.fail(
            "这段内容像是密码/验证码/支付类的，我不能替你输。你自己动手吧。",
            "Blocked:Secret",
        )

    # 底线：支付/收银台界面一律不打字
    if D.looks_like_payment():
        return C.fail(
            f"当前窗口「{D.foreground_title()}」看起来是支付/收银台页面，我不在这里打字。",
            "Blocked:Payment",
        )

    # 有指定窗口就先切过去（避免打进别的窗口）
    win = str(args.get("window") or "").strip()
    focused = ""
    if win:
        w = D.find_window(win)
        if not w:
            names = "、".join(x["title"][:18] for x in D.list_windows()[:6])
            return C.fail(f"没找到标题含「{win}」的窗口，没敢打字。现在开着的是：{names}", "NotFound")
        if not D.focus_window(w["hwnd"]):
            return C.fail(f"找到了「{w['title']}」但切不过去，没敢打字", "FocusFailed")
        focused = w["title"]

    before = D.foreground_title()

    try:
        n = D.type_text(text)
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"输入失败：{exc}", f"{type(exc).__name__}")

    after = D.foreground_title()
    return C.ok(
        f"往「{after or before}」输入了 {n} 个字",
        count=n, window=after or before, focused_before=before, focused_after=after,
    )


TOOL = {
    "name": "pc.type",
    "title": "打一段字",
    "desc": "往指定窗口里输入文字（支持中文）。一定要给 window 参数，它会先把那个窗口切到前台再打字，避免打进别的窗口。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要输入的文字，换行用 \\n"},
            "window": {"type": "string", "description": "目标窗口标题里的几个字，如 WorkBuddy。强烈建议给"},
        },
        "required": ["text"],
    },
    "run": C.guard(run),
}
