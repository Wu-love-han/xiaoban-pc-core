"""pc.context：把电脑上「用户正在干什么」说清楚。

小伴的需求：「我现在能看到 PC 的硬件信息，但看不到 PC 上的具体上下文
（比如用户在哪个窗口、在干什么）」
"""

from __future__ import annotations

import ctypes
import time
from typing import Any

from . import _common as C
from . import _desktop_common as D


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]


def _idle_seconds() -> int:
    """用户多久没动鼠标键盘了。"""
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return -1
        millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
        return max(0, int(millis / 1000))
    except Exception:  # noqa: BLE001
        return -1


def _summarize(wins: list[dict], fg: str, idle: int) -> str:
    """把窗口列表变成人话。"""
    parts = []
    if fg:
        parts.append(f"现在焦点在「{fg}」")
    if idle >= 0:
        if idle < 60:
            parts.append(f"你 {idle} 秒前还动过鼠标，人在")
        elif idle < 600:
            parts.append(f"你已经 {idle // 60} 分钟没动了")
        else:
            parts.append(f"你已经 {idle // 60} 分钟没动，可能走开了")

    # 按程序归类（去掉窗口标题的细节）
    apps: dict[str, int] = {}
    for w in wins:
        t = w.get("title") or ""
        key = t.split(" - ")[-1].strip() if " - " in t else t
        key = key[:24]
        apps[key] = apps.get(key, 0) + 1
    top = sorted(apps.items(), key=lambda kv: -kv[1])[:5]
    if top:
        parts.append("开着：" + "、".join(f"{k}（{v}）" if v > 1 else k for k, v in top))
    return "；".join(parts) + "。"


def run(args: dict, ctx: Any) -> dict:
    try:
        wins = D.list_windows()
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"读窗口失败：{exc}", f"{type(exc).__name__}")

    fg = D.foreground_title()
    idle = _idle_seconds()

    # 可选：只看某个关键词的窗口
    kw = str(args.get("keyword") or "").strip().lower()
    if kw:
        wins = [w for w in wins if kw in (w.get("title") or "").lower()]

    summary = _summarize(wins, fg, idle)
    detail = "\n".join(f"- {w['title'][:60]}" for w in wins[:12])

    return C.ok(
        summary + ("\n窗口明细：\n" + detail if detail else ""),
        foreground=fg,
        idle_seconds=idle,
        window_count=len(wins),
        windows=[w.get("title") for w in wins[:20]],
        at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )


TOOL = {
    "name": "pc.context",
    "title": "看用户在干什么",
    "desc": "了解电脑上用户当前在做什么：焦点窗口、开着哪些程序、多久没动鼠标键盘。想自然地关心用户、或判断该不该打扰时用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {"keyword": {"type": "string", "description": "只看标题含这个词的窗口（可省略）"}},
    },
    "run": C.guard(run),
}
