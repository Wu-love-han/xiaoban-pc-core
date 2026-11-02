"""审核智能体（Reviewer Agent）——用户笔记："也可加一个智能体审核"。

职责：在危险动作/对外发送/大额操作前，用一个独立的小模型调用做二次判断。
原则（用户笔记）："不用太多审核"——只审真正危险的，普通操作不打扰。

分级：
- low   ：只读、查询类 → 不审，直接过
- mid   ：写文件、跑命令、点手机 → 记录日志，不阻塞
- high  ：删除、对外发送、支付相关 → 必须审（默认拦截，等用户确认）
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("pccore.reviewer")

# 高危动作关键词（工具名或参数命中即 high）
_HIGH_PATTERNS = [
    r"delete|remove|rm_|uninstall",          # 删除
    r"pay|transfer|bank",                     # 支付转账
    r"send_message|send_sms|call",            # 对外发送/拨号
    r"publish|upload|post_",                  # 对外发布
]

# 中危动作
_MID_PATTERNS = [
    r"write_file|append_file|mkdir|shell|pwsh|bash",
    r"phone\.tap|phone\.swipe|phone\.input_text|phone\.open_app",
    r"open_app|control",
]


def classify(tool_name: str, args: dict | None = None) -> str:
    """给一个工具调用定级：low / mid / high。"""
    name = (tool_name or "").lower()
    blob = name
    if args:
        try:
            blob += " " + " ".join(str(v) for v in args.values())
        except Exception:  # noqa: BLE001
            pass
    for p in _HIGH_PATTERNS:
        if re.search(p, blob, re.I):
            return "high"
    for p in _MID_PATTERNS:
        if re.search(p, name, re.I):
            return "mid"
    return "low"


def should_block(tool_name: str, args: dict | None = None) -> tuple[bool, str]:
    """返回 (是否拦截, 原因)。high 级默认拦截，等用户确认。"""
    level = classify(tool_name, args)
    if level == "high":
        return True, f"审核智能体：{tool_name} 属于高危操作，需要你确认"
    return False, ""
