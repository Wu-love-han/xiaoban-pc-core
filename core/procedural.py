"""程序记忆（Procedural Memory）——记住"哪类问题用什么工具序列解决"。

参考 AI Agent Memory Architecture (TiDB Playbook) 的四种记忆分层：
    working / short-term / long-term / **procedural**

程序记忆存的是"做法"而不是"事实"：
- 事实（long_term）：用户喜欢喝咖啡
- 做法（procedural）：问时间 -> 用 sys.time；列文件 -> 用 pc.list_dir

收益：同类问题第二次遇到时，直接把上次成功的工具序列注入提示，模型不用重新摸索。

库：data/procedural.db（独立，不碰主库和 memory.db）
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .paths import DATA_DIR

logger = logging.getLogger("pccore.procedural")

DB_FILE = DATA_DIR / "procedural.db"
_lock = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS procedures (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    intent        TEXT NOT NULL,            -- 意图关键词（归一化后的短句）
    tool_chain    TEXT NOT NULL,            -- JSON 数组：["pc.list_dir","pc.read_file"]
    success_count INTEGER NOT NULL DEFAULT 1,
    fail_count    INTEGER NOT NULL DEFAULT 0,
    last_used_at  INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_intent_chain ON procedures(intent, tool_chain);
"""


def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_FILE), timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    try:
        with _lock, _conn() as c:
            c.executescript(_SCHEMA)
    except Exception:  # noqa: BLE001
        logger.exception("程序记忆建表失败")


def _normalize_intent(text: str) -> str:
    """把用户话压成意图关键词：去标点、去空白、截断。"""
    import re

    t = re.sub(r"[\s\u3000，。！？、,.!?;；:：\"'“”‘’()（）\[\]【】]+", "", (text or "").lower())
    return t[:40]


def record(intent_text: str, tool_chain: list[str], success: bool = True) -> None:
    """记一次"这类问题用了这串工具"。同类合并，成功/失败分别累加。"""
    if not tool_chain:
        return
    import json
    import time

    key = _normalize_intent(intent_text)
    if not key:
        return
    chain = json.dumps(tool_chain[:10], ensure_ascii=False)
    now = int(time.time() * 1000)
    try:
        init()
        with _lock, _conn() as c:
            row = c.execute(
                "SELECT id, success_count, fail_count FROM procedures WHERE intent=? AND tool_chain=?",
                (key, chain),
            ).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO procedures(intent,tool_chain,success_count,fail_count,last_used_at,created_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (key, chain, 1 if success else 0, 0 if success else 1, now, now),
                )
            else:
                c.execute(
                    "UPDATE procedures SET success_count=success_count+?, fail_count=fail_count+?, last_used_at=?"
                    " WHERE id=?",
                    (1 if success else 0, 0 if success else 1, now, row["id"]),
                )
    except Exception:  # noqa: BLE001
        logger.warning("写程序记忆失败（忽略）", exc_info=True)


def suggest(intent_text: str, limit: int = 2) -> list[dict]:
    """查"这类问题以前成功用过什么工具序列"。只返回净成功过的。"""
    import json

    key = _normalize_intent(intent_text)
    if not key:
        return []
    try:
        init()
        with _lock, _conn() as c:
            rows = c.execute(
                "SELECT tool_chain, success_count, fail_count FROM procedures"
                " WHERE intent LIKE ? AND success_count > fail_count"
                " ORDER BY success_count DESC, last_used_at DESC LIMIT ?",
                (f"%{key[:12]}%", max(1, int(limit))),
            ).fetchall()
        out = []
        for r in rows:
            try:
                chain = json.loads(r["tool_chain"])
            except Exception:  # noqa: BLE001
                chain = []
            if chain:
                out.append({
                    "tools": chain,
                    "success": int(r["success_count"]),
                    "fail": int(r["fail_count"]),
                })
        return out
    except Exception:  # noqa: BLE001
        logger.warning("查程序记忆失败（忽略）", exc_info=True)
        return []


def prompt_snippet(intent_text: str) -> str:
    """给 system prompt 的一小段：以前这类事是这么做的。"""
    hits = suggest(intent_text, limit=2)
    if not hits:
        return ""
    lines = []
    for h in hits:
        steps = " -> ".join(h["tools"][:6])
        lines.append(f"- {steps}（成功 {h['success']} 次）")
    return "【以前类似的事你是这么做的】\n" + "\n".join(lines)


def count() -> int:
    try:
        init()
        with _lock, _conn() as c:
            return int(c.execute("SELECT COUNT(*) AS n FROM procedures").fetchone()["n"])
    except Exception:  # noqa: BLE001
        return 0
