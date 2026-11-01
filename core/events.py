"""事件常量与落库薄封装。

事件名是和前端约定的「法律」，集中在这里避免各处写错字。
实际落库走 core.db.add_event。
"""

from __future__ import annotations

from . import db

# 契约第四节定义的全部事件名
SESSION = "session"
THINKING = "thinking"
CONTENT = "content"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
APPROVAL = "approval"
TURN_END = "turn_end"
ERROR = "error"

ALL = (SESSION, THINKING, CONTENT, TOOL_CALL, TOOL_RESULT, APPROVAL, TURN_END, ERROR)


def record(kind: str, payload: dict, session_id: str = "") -> int:
    """落一条事件（前端历史/排查用）。"""
    return db.add_event(kind, payload, session_id)
