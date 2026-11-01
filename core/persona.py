"""人格加载器。

唯一权威是 docs/PERSONA.md 里的「## 系统提示」段落。
代码里**不许**再出现任何人格文案——要改人格只改那个 md 文件。

带 mtime 缓存：改完 md 下一轮就生效，不用重启。
"""

from __future__ import annotations

import logging
from pathlib import Path

from .paths import PERSONA_FILE

logger = logging.getLogger("pccore.persona")

_MARKER = "## 系统提示"
_cache_text: str = ""
_cache_mtime: float = -1.0

# 读不到人格文件时的兜底（保证服务能起来，但日志会报警）
_FALLBACK = (
    "你是「小伴」，一个住在用户 Windows 电脑里的伙伴。"
    "你说话口语、短句，一次一两句。你能调用工具真的操作电脑。"
    "用户让你做事就调工具，只是聊天就正常聊。"
)


def _read_raw() -> str:
    global _cache_text, _cache_mtime
    try:
        mtime = PERSONA_FILE.stat().st_mtime
    except OSError:
        logger.error("人格文件不存在：%s", PERSONA_FILE)
        return _FALLBACK
    if mtime == _cache_mtime and _cache_text:
        return _cache_text
    try:
        raw = PERSONA_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("人格文件读取失败：%s", exc)
        return _FALLBACK

    idx = raw.find(_MARKER)
    text = raw[idx + len(_MARKER):] if idx >= 0 else raw
    # 去掉紧随标记的 HTML 注释块（那是写给维护者看的说明）
    text = _strip_html_comments(text).strip()
    if not text:
        logger.warning("人格文件里「%s」之后是空的，用兜底人格", _MARKER)
        text = _FALLBACK
    _cache_text = text
    _cache_mtime = mtime
    return text


def _strip_html_comments(s: str) -> str:
    out: list[str] = []
    i = 0
    while True:
        start = s.find("<!--", i)
        if start < 0:
            out.append(s[i:])
            break
        out.append(s[i:start])
        end = s.find("-->", start + 4)
        if end < 0:
            break
        i = end + 3
    return "".join(out)


def base_prompt() -> str:
    """人格本体（不含工具清单）。"""
    return _read_raw()


def build_system_prompt(tool_catalog: str = "", memory_block: str = "") -> str:
    """拼最终 system prompt：人格 + 当前工具清单 + 记忆。

    工具清单每轮动态生成，所以新加工具模型立刻知道。
    """
    parts = [base_prompt()]
    if tool_catalog:
        parts.append("\n【你现在能用的工具】\n" + tool_catalog)
    if memory_block:
        parts.append("\n【你还记得】\n" + memory_block)
    return "\n".join(parts)


def reload() -> None:
    """强制重读（测试/热更用）。"""
    global _cache_mtime
    _cache_mtime = -1.0
    _read_raw()
