"""三端同步中枢（Sync Hub）。

用户需求：
    "是软件是终端，我也能通过手机或者机器人进行命令下达，
     同步3端指令、日志、对话和记忆"

架构：
    PC 既是「中枢」也是「终端」；手机、ESP32 都是终端。
    所有终端连 PC 的 HTTP API，PC 负责落库和分发。

同步的四类数据：
    1. 指令 commands  —— 任何终端可下发，目标终端领取执行并回结果
    2. 日志 logs      —— 任何终端可写，所有终端可按游标拉增量
    3. 对话 messages  —— 复用主库 messages（PC 上的对话三端都能拉）
    4. 记忆 memory    —— 复用 memory_engine（短期/长期/印象/情绪）

库：data/sync.db（独立，不碰主库）
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from typing import Any

from .paths import DATA_DIR

logger = logging.getLogger("pccore.sync")

DB_FILE = DATA_DIR / "sync.db"
_lock = threading.RLock()

ONLINE_WINDOW_MS = 90_000  # 90 秒内有心跳算在线

_SCHEMA = """
CREATE TABLE IF NOT EXISTS terminals (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'unknown',   -- pc / phone / robot
    last_seen   INTEGER NOT NULL DEFAULT 0,
    meta        TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS commands (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_tid    TEXT NOT NULL,
    to_tid      TEXT NOT NULL,
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending/delivered/done/failed
    result      TEXT NOT NULL DEFAULT '',
    created_ms  INTEGER NOT NULL,
    done_ms     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sync_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tid         TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'info',
    text        TEXT NOT NULL DEFAULT '',
    data        TEXT NOT NULL DEFAULT '{}',
    ts_ms       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cmd_to ON commands(to_tid, status);
CREATE INDEX IF NOT EXISTS idx_log_ts ON sync_logs(id);
"""


def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_FILE), timeout=30.0, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("PRAGMA synchronous=NORMAL")
    except Exception:  # noqa: BLE001
        pass
    return c


def init() -> None:
    try:
        with _lock, _conn() as c:
            c.executescript(_SCHEMA)
    except Exception:  # noqa: BLE001
        logger.exception("同步库建表失败")


def _now() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------- 终端

def register(tid: str, name: str = "", kind: str = "unknown", meta: dict | None = None) -> dict:
    tid = (tid or "").strip()
    if not tid:
        raise ValueError("终端 id 不能为空")
    init()
    with _lock, _conn() as c:
        row = c.execute("SELECT id FROM terminals WHERE id=?", (tid,)).fetchone()
        if row is None:
            c.execute(
                "INSERT INTO terminals(id,name,kind,last_seen,meta) VALUES(?,?,?,?,?)",
                (tid, name or tid, kind, _now(), json.dumps(meta or {}, ensure_ascii=False)),
            )
        else:
            c.execute(
                "UPDATE terminals SET name=?, kind=?, last_seen=?, meta=? WHERE id=?",
                (name or tid, kind, _now(), json.dumps(meta or {}, ensure_ascii=False), tid),
            )
    return {"id": tid, "name": name or tid, "kind": kind}


def heartbeat(tid: str) -> bool:
    init()
    with _lock, _conn() as c:
        cur = c.execute("UPDATE terminals SET last_seen=? WHERE id=?", (_now(), tid))
        return cur.rowcount > 0


def list_terminals() -> list[dict]:
    init()
    now = _now()
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM terminals ORDER BY kind, id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["online"] = (now - int(d.get("last_seen") or 0)) < ONLINE_WINDOW_MS
        try:
            d["meta"] = json.loads(d.get("meta") or "{}")
        except Exception:  # noqa: BLE001
            d["meta"] = {}
        out.append(d)
    return out


# ---------------------------------------------------------------- 指令

def push_command(from_tid: str, to_tid: str, text: str) -> dict:
    from_tid = (from_tid or "pc").strip()
    to_tid = (to_tid or "").strip()
    text = (text or "").strip()
    if not to_tid:
        raise ValueError("目标终端不能为空")
    if not text:
        raise ValueError("指令内容不能为空")
    init()
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO commands(from_tid,to_tid,text,status,created_ms) VALUES(?,?,?,'pending',?)",
            (from_tid, to_tid, text[:2000], _now()),
        )
        cid = cur.lastrowid
    log(from_tid, "command", f"→{to_tid}: {text[:80]}", {"command_id": cid})
    return {"id": cid, "from": from_tid, "to": to_tid, "text": text, "status": "pending"}


def claim_commands(tid: str, limit: int = 10) -> list[dict]:
    """目标终端领取待执行指令，标记为 delivered。"""
    init()
    limit = max(1, min(50, int(limit)))
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM commands WHERE to_tid=? AND status='pending' ORDER BY id LIMIT ?",
            (tid, limit),
        ).fetchall()
        out = [dict(r) for r in rows]
        for r in out:
            c.execute("UPDATE commands SET status='delivered' WHERE id=?", (r["id"],))
    if out:
        log(tid, "claim", f"领取 {len(out)} 条指令")
    return out


def finish_command(cid: int, ok: bool, result: str = "") -> bool:
    init()
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE commands SET status=?, result=?, done_ms=? WHERE id=?",
            ("done" if ok else "failed", (result or "")[:2000], _now(), int(cid)),
        )
        return cur.rowcount > 0


def list_commands(limit: int = 30, to_tid: str = "") -> list[dict]:
    init()
    limit = max(1, min(200, int(limit)))
    with _lock, _conn() as c:
        if to_tid:
            rows = c.execute(
                "SELECT * FROM commands WHERE to_tid=? ORDER BY id DESC LIMIT ?", (to_tid, limit)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM commands ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- 日志

def log(tid: str, kind: str, text: str, data: dict | None = None) -> int:
    init()
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO sync_logs(tid,kind,text,data,ts_ms) VALUES(?,?,?,?,?)",
            ((tid or "?"), (kind or "info")[:32], (text or "")[:2000],
             json.dumps(data or {}, ensure_ascii=False), _now()),
        )
        return int(cur.lastrowid)


def pull_logs(since_id: int = 0, limit: int = 50) -> list[dict]:
    init()
    limit = max(1, min(200, int(limit)))
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM sync_logs WHERE id>? ORDER BY id LIMIT ?", (int(since_id), limit)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["data"] = json.loads(d.get("data") or "{}")
        except Exception:  # noqa: BLE001
            d["data"] = {}
        out.append(d)
    return out


def log_cursor() -> int:
    init()
    with _lock, _conn() as c:
        row = c.execute("SELECT MAX(id) AS m FROM sync_logs").fetchone()
    return int((row["m"] if row and row["m"] else 0))


# ---------------------------------------------------------------- 对话 & 记忆（代理主库）

def pull_conversations(since_ms: int = 0, limit: int = 20) -> list[dict]:
    """拉 PC 上的对话（复用主库 messages）。"""
    try:
        from . import db  # noqa: PLC0415

        rows = db.query(
            "SELECT id, session_id, role, content, created_at FROM messages "
            "WHERE created_at > ? ORDER BY id DESC LIMIT ?",
            (int(since_ms), max(1, min(100, int(limit)))),
        )
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        logger.warning("拉对话失败", exc_info=True)
        return []


def memory_snapshot() -> dict:
    """记忆快照（复用 memory_engine）。"""
    try:
        from . import memory_engine  # noqa: PLC0415

        st = memory_engine.get_state()
        return {
            "short_term": st.get("short_term", {}),
            "long_term": st.get("long_term", {}),
            "impressions": st.get("impressions", []),
            "affinity": st.get("affinity"),
            "mood": st.get("mood", {}),
        }
    except Exception:  # noqa: BLE001
        logger.warning("读记忆快照失败", exc_info=True)
        return {}


# ---------------------------------------------------------------- 总览

def state() -> dict:
    init()
    now = _now()
    with _lock, _conn() as c:
        terminals = c.execute("SELECT COUNT(*) AS n FROM terminals").fetchone()["n"]
        online = c.execute(
            "SELECT COUNT(*) AS n FROM terminals WHERE last_seen>?", (now - ONLINE_WINDOW_MS,)
        ).fetchone()["n"]
        pending = c.execute(
            "SELECT COUNT(*) AS n FROM commands WHERE status IN ('pending','delivered')"
        ).fetchone()["n"]
        logs = c.execute("SELECT COUNT(*) AS n FROM sync_logs").fetchone()["n"]
        cursor = c.execute("SELECT MAX(id) AS m FROM sync_logs").fetchone()["m"]
    return {
        "terminals": int(terminals),
        "online": int(online),
        "pending_commands": int(pending),
        "logs": int(logs),
        "log_cursor": int(cursor or 0),
        "db": str(DB_FILE),
    }
