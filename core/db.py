"""SQLite 数据层。

为什么用裸 sqlite3 而不是 ORM：这个工程的表很少、查询都是点查，
ORM 只会增加一层看不懂的东西。裸 SQL + 每线程一个连接就够了。

要点：
- WAL 模式（读写不互相阻塞），`synchronous=NORMAL` 换速度。
- 每个线程一个连接（sqlite3 连接不能跨线程）。
- 所有写操作串行化（_write_lock），避免 database is locked。
"""

from __future__ import annotations

import json
import random
import sqlite3
import string
import threading
import time
from typing import Any, Iterable

from .paths import DB_FILE, ensure_dirs

_local = threading.local()
_write_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    thinking    TEXT NOT NULL DEFAULT '',
    tool_calls  TEXT NOT NULL DEFAULT '[]',
    created_at  INTEGER NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS tool_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    call_id     TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    args        TEXT NOT NULL DEFAULT '{}',
    ok          INTEGER NOT NULL DEFAULT 0,
    output      TEXT NOT NULL DEFAULT '',
    ms          INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_toolruns_session ON tool_runs(session_id, id);

CREATE TABLE IF NOT EXISTS approvals (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    call_id     TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    args        TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  INTEGER NOT NULL,
    decided_at  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, created_at);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}',
    ts          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, id);

CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope       TEXT NOT NULL DEFAULT 'global',
    key         TEXT NOT NULL DEFAULT '',
    value       TEXT NOT NULL DEFAULT '',
    weight      REAL NOT NULL DEFAULT 1.0,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope, weight DESC);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str, n: int = 12) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return prefix + "".join(random.choice(alphabet) for _ in range(n))


def conn() -> sqlite3.Connection:
    """取当前线程的连接（懒建）。"""
    c = getattr(_local, "conn", None)
    if c is None:
        ensure_dirs()
        c = sqlite3.connect(str(DB_FILE), timeout=30.0, isolation_level=None, check_same_thread=False)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")
            c.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=15000")
        _local.conn = c
    return c


def init() -> None:
    c = conn()
    with _write_lock:
        c.executescript(SCHEMA)


def _write(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    c = conn()
    with _write_lock:
        return c.execute(sql, tuple(params))


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return list(conn().execute(sql, tuple(params)).fetchall())


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return conn().execute(sql, tuple(params)).fetchone()


def _loads(s: Any, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


# ---------------------------------------------------------------- sessions

def create_session(title: str = "") -> dict:
    sid = new_id("s_")
    ts = now_ms()
    _write(
        "INSERT INTO sessions(id,title,created_at,updated_at,meta) VALUES(?,?,?,?,?)",
        (sid, title[:60], ts, ts, "{}"),
    )
    return {"id": sid, "title": title[:60], "created_at": ts, "updated_at": ts}


def get_session(sid: str) -> dict | None:
    r = query_one("SELECT * FROM sessions WHERE id=?", (sid,))
    if not r:
        return None
    d = dict(r)
    d["meta"] = _loads(d.get("meta"), {})
    return d


def touch_session(sid: str, title: str | None = None) -> None:
    if title:
        _write("UPDATE sessions SET updated_at=?, title=? WHERE id=?", (now_ms(), title[:60], sid))
    else:
        _write("UPDATE sessions SET updated_at=? WHERE id=?", (now_ms(), sid))


def list_sessions(limit: int = 30) -> list[dict]:
    rows = query(
        """SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS msg_count
           FROM sessions s ORDER BY s.updated_at DESC LIMIT ?""",
        (limit,),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = _loads(d.get("meta"), {})
        out.append(d)
    return out


def delete_session(sid: str) -> None:
    with _write_lock:
        for t in ("messages", "tool_runs", "approvals", "events"):
            _write(f"DELETE FROM {t} WHERE session_id=?", (sid,))
        _write("DELETE FROM sessions WHERE id=?", (sid,))


# ---------------------------------------------------------------- messages

def add_message(
    session_id: str,
    role: str,
    content: str,
    *,
    thinking: str = "",
    tool_calls: list | None = None,
    meta: dict | None = None,
) -> int:
    cur = _write(
        """INSERT INTO messages(session_id,role,content,thinking,tool_calls,created_at,meta)
           VALUES(?,?,?,?,?,?,?)""",
        (
            session_id,
            role,
            content or "",
            thinking or "",
            json.dumps(tool_calls or [], ensure_ascii=False),
            now_ms(),
            json.dumps(meta or {}, ensure_ascii=False),
        ),
    )
    return int(cur.lastrowid or 0)


def list_messages(session_id: str, limit: int = 100) -> list[dict]:
    rows = query(
        "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    )
    rows = list(reversed(rows))
    out = []
    for r in rows:
        d = dict(r)
        d["tool_calls"] = _loads(d.get("tool_calls"), [])
        d["meta"] = _loads(d.get("meta"), {})
        out.append(d)
    return out


def history_for_model(session_id: str, turns: int = 8) -> list[dict]:
    """给模型的历史：只取 user/assistant 的纯文本，最近 N 轮。"""
    rows = query(
        "SELECT role,content FROM messages WHERE session_id=? AND role IN ('user','assistant') "
        "ORDER BY id DESC LIMIT ?",
        (session_id, turns * 2),
    )
    rows = list(reversed(rows))
    return [{"role": r["role"], "content": r["content"]} for r in rows if r["content"]]


# ---------------------------------------------------------------- tool runs

def add_tool_run(
    session_id: str, call_id: str, name: str, args: dict, ok: bool, output: str, ms: int
) -> int:
    cur = _write(
        """INSERT INTO tool_runs(session_id,call_id,name,args,ok,output,ms,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (
            session_id,
            call_id,
            name,
            json.dumps(args or {}, ensure_ascii=False),
            int(bool(ok)),
            (output or "")[:4000],
            int(ms),
            now_ms(),
        ),
    )
    return int(cur.lastrowid or 0)


def list_tool_runs(session_id: str, limit: int = 50) -> list[dict]:
    rows = query(
        "SELECT * FROM tool_runs WHERE session_id=? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["args"] = _loads(d.get("args"), {})
        d["ok"] = bool(d["ok"])
        out.append(d)
    return out


# ---------------------------------------------------------------- approvals

def create_approval(session_id: str, call_id: str, name: str, args: dict) -> dict:
    aid = new_id("a_")
    ts = now_ms()
    _write(
        """INSERT INTO approvals(id,session_id,call_id,name,args,status,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (aid, session_id, call_id, name, json.dumps(args or {}, ensure_ascii=False), "pending", ts),
    )
    return {
        "id": aid, "session_id": session_id, "call_id": call_id,
        "name": name, "args": args or {}, "status": "pending", "created_at": ts,
    }


def get_approval(aid: str) -> dict | None:
    r = query_one("SELECT * FROM approvals WHERE id=?", (aid,))
    if not r:
        return None
    d = dict(r)
    d["args"] = _loads(d.get("args"), {})
    return d


def decide_approval(aid: str, decision: str) -> bool:
    """只有 pending 能被改，避免重复点击/超时竞态。"""
    cur = _write(
        "UPDATE approvals SET status=?, decided_at=? WHERE id=? AND status='pending'",
        (decision, now_ms(), aid),
    )
    return cur.rowcount > 0


def list_approvals(status: str = "pending", limit: int = 50) -> list[dict]:
    if status:
        rows = query(
            "SELECT * FROM approvals WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = query("SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        d = dict(r)
        d["args"] = _loads(d.get("args"), {})
        out.append(d)
    return out


def expire_approvals(older_than_ms: int) -> int:
    cutoff = now_ms() - older_than_ms
    cur = _write(
        "UPDATE approvals SET status='expired', decided_at=? WHERE status='pending' AND created_at<?",
        (now_ms(), cutoff),
    )
    return cur.rowcount


# ---------------------------------------------------------------- events

def add_event(kind: str, payload: dict, session_id: str = "") -> int:
    cur = _write(
        "INSERT INTO events(session_id,kind,payload,ts) VALUES(?,?,?,?)",
        (session_id, kind, json.dumps(payload or {}, ensure_ascii=False), now_ms()),
    )
    return int(cur.lastrowid or 0)


def list_events(limit: int = 50, session_id: str = "") -> list[dict]:
    if session_id:
        rows = query(
            "SELECT * FROM events WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
    else:
        rows = query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = _loads(d.get("payload"), {})
        out.append(d)
    return out


# ---------------------------------------------------------------- memories

def remember(key: str, value: str, scope: str = "global") -> dict:
    ts = now_ms()
    row = query_one("SELECT id FROM memories WHERE scope=? AND key=?", (scope, key))
    if row:
        _write(
            "UPDATE memories SET value=?, updated_at=?, weight=weight+0.2 WHERE id=?",
            (value, ts, row["id"]),
        )
        return {"id": row["id"], "key": key, "value": value, "updated": True}
    cur = _write(
        "INSERT INTO memories(scope,key,value,weight,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (scope, key, value, 1.0, ts, ts),
    )
    return {"id": int(cur.lastrowid or 0), "key": key, "value": value, "updated": False}


def recall(query_text: str, scope: str = "global", limit: int = 6) -> list[dict]:
    """关键词召回 + 权重排序。刻意不做向量检索（8GB 显存要留给模型）。"""
    q = (query_text or "").strip()
    if not q:
        rows = query(
            "SELECT * FROM memories WHERE scope IN (?, 'global') "
            "ORDER BY weight DESC, updated_at DESC LIMIT ?",
            (scope, limit),
        )
    else:
        terms = {q}
        for i in range(len(q) - 1):
            terms.add(q[i : i + 2])
        terms = [t for t in terms if t.strip()][:12]
        like = " OR ".join(["key LIKE ? OR value LIKE ?"] * len(terms))
        params: list[Any] = []
        for t in terms:
            params += [f"%{t}%", f"%{t}%"]
        params += [scope, limit]
        rows = query(
            f"SELECT * FROM memories WHERE ({like}) AND scope IN (?, 'global') "
            f"ORDER BY weight DESC, updated_at DESC LIMIT ?",
            params,
        )
    out = [dict(r) for r in rows]
    for d in out:
        _write("UPDATE memories SET weight=weight+0.1 WHERE id=?", (d["id"],))
    return out


def list_memories(scope: str = "global", limit: int = 100) -> list[dict]:
    if scope:
        rows = query(
            "SELECT * FROM memories WHERE scope=? ORDER BY weight DESC, updated_at DESC LIMIT ?",
            (scope, limit),
        )
    else:
        rows = query("SELECT * FROM memories ORDER BY weight DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def forget(mem_id: int) -> bool:
    cur = _write("DELETE FROM memories WHERE id=?", (mem_id,))
    return cur.rowcount > 0


def stats() -> dict:
    def n(t: str) -> int:
        r = query_one(f"SELECT COUNT(*) AS c FROM {t}")
        return int(r["c"]) if r else 0

    return {
        "sessions": n("sessions"),
        "messages": n("messages"),
        "tool_runs": n("tool_runs"),
        "approvals": n("approvals"),
        "events": n("events"),
        "memories": n("memories"),
        "db_file": str(DB_FILE),
    }
