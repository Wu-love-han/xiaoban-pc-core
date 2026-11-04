"""实时活动：小伴现在在干什么。

用户需求：「他在做什么会告诉我，并自己实时更新」

做法：
- brain 每次调工具前后打点（begin / end）
- 前端每 2 秒拉一次 /api/activity，显示成一行状态
- 同时记最近 N 条动作流水，能看到「刚刚做了什么」
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("pccore.activity")

_lock = threading.RLock()
_state: dict = {
    "busy": False,
    "session_id": "",
    "tool": "",
    "title": "",
    "args_hint": "",
    "started_ms": 0,
    "step": 0,
    "last_text": "",       # 最近一句它说的话
    "last_text_ms": 0,
}
_recent: list[dict] = []
MAX_RECENT = 30


def begin(session_id: str, tool: str, title: str = "", args_hint: str = "") -> None:
    """开始一个动作。"""
    with _lock:
        _state.update({
            "busy": True,
            "session_id": session_id,
            "tool": tool,
            "title": title or tool,
            "args_hint": (args_hint or "")[:120],
            "started_ms": int(time.time() * 1000),
        })
        _state["step"] = int(_state.get("step") or 0) + 1


def end(ok: bool = True, note: str = "") -> None:
    """动作结束。"""
    with _lock:
        if not _state["busy"]:
            return
        item = {
            "tool": _state["tool"],
            "title": _state["title"],
            "ok": bool(ok),
            "ms": int(time.time() * 1000) - int(_state["started_ms"] or 0),
            "note": (note or "")[:100],
            "at": int(time.time() * 1000),
        }
        _recent.append(item)
        if len(_recent) > MAX_RECENT:
            del _recent[: len(_recent) - MAX_RECENT]
        _state.update({"busy": False, "tool": "", "title": "", "args_hint": ""})


def say(text: str) -> None:
    """记下它最近说的一句话（前端可以显示「它刚说了什么」）。"""
    t = (text or "").strip()
    if not t:
        return
    with _lock:
        _state["last_text"] = t[:200]
        _state["last_text_ms"] = int(time.time() * 1000)


def reset() -> None:
    with _lock:
        _state.update({
            "busy": False, "session_id": "", "tool": "", "title": "",
            "args_hint": "", "started_ms": 0, "step": 0,
        })


def snapshot() -> dict:
    """当前状态 + 最近动作。"""
    with _lock:
        s = dict(_state)
        s["elapsed_ms"] = (
            int(time.time() * 1000) - int(s["started_ms"]) if s["busy"] else 0
        )
        s["recent"] = list(_recent[-12:])
    return s


# ---------------------------------------------------------------- 屏幕占用通知

# 这些工具会真的动屏幕/鼠标键盘，用户会看到画面跳
SCREEN_TOOLS = {
    "pc.click", "pc.click_text", "pc.type", "pc.hotkey",
    "pc.focus_window", "pc.open_app", "pc.screen", "pc.look",
    "phone.click_text", "phone.tap", "phone.swipe", "phone.input_text",
    "phone.key", "phone.open_app", "phone.find_tap",
}

_announced: dict = {"turn": "", "said": False}


def needs_screen_notice(tool: str) -> bool:
    return tool in SCREEN_TOOLS


def mark_announced(turn_key: str) -> bool:
    """一轮里只通知一次。返回 True 表示这次要通知。"""
    with _lock:
        if _announced.get("turn") == turn_key and _announced.get("said"):
            return False
        _announced["turn"] = turn_key
        _announced["said"] = True
        return True


def reset_turn() -> None:
    with _lock:
        _announced["said"] = False
