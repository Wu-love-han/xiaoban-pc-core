"""三端 AI 身份与互相通信。

架构：
  小伴（PC）   —— 大脑，协调者，记忆主库
  小随（手机） —— 手，随身，能操控手机和电脑
  小动（机器人）—— 身体，感知环境（待做）

三个 AI 共同扮演「小伴」这一个陪伴角色，但各有分工。
它们通过 PC 中转互相联系（手机和机器人不直连）。

用户需求：
  「你们每个 ai 都可以联系（通过 pc 端），共同办好项目和记忆」
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger("pccore.agents")

_lock = threading.RLock()
_conn_local = threading.local()
_initialized = False

# 三个 AI 的身份
ROSTER = {
    "pc": {
        "name": "小伴",
        "role": "大脑",
        "desc": "住在电脑里，能操作电脑、协调另外两个、记着所有事",
        "caps": ["控电脑", "记忆主库", "协调", "插件管理", "网页"],
    },
    "phone": {
        "name": "小随",
        "role": "手",
        "desc": "住在手机里，跟着 WH 走，能操作手机也能遥控电脑",
        "caps": ["控手机", "控电脑", "离线工作", "本地插件缓存", "主动汇报"],
    },
    "robot": {
        "name": "小动",
        "role": "身体",
        "desc": "ESP32 机器人，能看能动能说话（待做）",
        "caps": ["移动", "感知环境", "语音"],
    },
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    kind TEXT DEFAULT 'note',
    content TEXT NOT NULL,
    meta TEXT DEFAULT '',
    status TEXT DEFAULT 'unread',
    created_ms INTEGER NOT NULL,
    read_ms INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_agent_to ON agent_messages(to_id, status, created_ms);
CREATE INDEX IF NOT EXISTS idx_agent_created ON agent_messages(created_ms);
"""


def _db_path() -> Path:
    from .paths import DATA_DIR  # noqa: PLC0415

    return DATA_DIR / "agents.db"


def _conn() -> sqlite3.Connection:
    c = getattr(_conn_local, "conn", None)
    if c is None:
        p = _db_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(p), timeout=30.0, isolation_level=None, check_same_thread=False)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")
            c.execute("PRAGMA synchronous=NORMAL")
        except Exception:  # noqa: BLE001
            pass
        c.row_factory = sqlite3.Row
        _conn_local.conn = c
    return c


def init() -> None:
    global _initialized
    if _initialized:
        return
    with _lock:
        if _initialized:
            return
        try:
            _conn().executescript(_SCHEMA)
            _initialized = True
        except Exception:  # noqa: BLE001
            logger.exception("agents.db 初始化失败")


def who(agent_id: str) -> dict:
    return ROSTER.get(agent_id) or {"name": agent_id, "role": "?", "desc": "", "caps": []}


def send(from_id: str, to_id: str, content: str, kind: str = "note", meta: dict | None = None) -> dict:
    """一个 AI 给另一个 AI 发消息。"""
    init()
    if from_id not in ROSTER or to_id not in ROSTER:
        raise ValueError(f"不认识的 AI：{from_id} → {to_id}")
    if from_id == to_id:
        raise ValueError("不能发给自己")
    text = (content or "").strip()
    if not text:
        raise ValueError("内容不能为空")
    ts = int(time.time() * 1000)
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO agent_messages(from_id,to_id,kind,content,meta,status,created_ms) "
            "VALUES(?,?,?,?,?,'unread',?)",
            (from_id, to_id, (kind or "note")[:20], text[:4000],
             json.dumps(meta or {}, ensure_ascii=False)[:2000], ts),
        )
        mid = cur.lastrowid
    logger.info("[%s → %s] %s", who(from_id)["name"], who(to_id)["name"], text[:60])
    return {"id": mid, "from": from_id, "to": to_id, "content": text, "created_ms": ts}


def inbox(agent_id: str, limit: int = 20, unread_only: bool = True) -> list[dict]:
    """看自己的收件箱。"""
    init()
    limit = max(1, min(100, int(limit)))
    sql = "SELECT * FROM agent_messages WHERE to_id=?"
    args: list = [agent_id]
    if unread_only:
        sql += " AND status='unread'"
    sql += " ORDER BY created_ms DESC LIMIT ?"
    args.append(limit)
    with _lock:
        rows = _conn().execute(sql, tuple(args)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["from_name"] = who(d["from_id"])["name"]
        out.append(d)
    return out


def mark_read(agent_id: str, msg_ids: list[int] | None = None) -> int:
    """标记已读。不传 id 就全标。"""
    init()
    ts = int(time.time() * 1000)
    with _lock, _conn() as c:
        if msg_ids:
            ph = ",".join("?" * len(msg_ids))
            cur = c.execute(
                f"UPDATE agent_messages SET status='read', read_ms=? "
                f"WHERE to_id=? AND status='unread' AND id IN ({ph})",
                tuple([ts, agent_id] + list(msg_ids)),
            )
        else:
            cur = c.execute(
                "UPDATE agent_messages SET status='read', read_ms=? WHERE to_id=? AND status='unread'",
                (ts, agent_id),
            )
        return cur.rowcount


def recent(limit: int = 30) -> list[dict]:
    """所有 AI 之间的最近消息（给用户看协作记录）。"""
    init()
    limit = max(1, min(200, int(limit)))
    with _lock:
        rows = _conn().execute(
            "SELECT * FROM agent_messages ORDER BY created_ms DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["from_name"] = who(d["from_id"])["name"]
        d["to_name"] = who(d["to_id"])["name"]
        out.append(d)
    return out


def state() -> dict:
    init()
    with _lock:
        rows = _conn().execute(
            "SELECT to_id, COUNT(*) AS n FROM agent_messages WHERE status='unread' GROUP BY to_id"
        ).fetchall()
    unread = {r["to_id"]: int(r["n"]) for r in rows}
    return {
        "roster": ROSTER,
        "unread": unread,
    }
