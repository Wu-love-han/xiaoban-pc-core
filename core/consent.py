"""人工确认（Consent）——AI 不能自己批准的事，交给用户在后台点。

为什么需要：
小伴能改自己的代码，但「底线文件」（审核红线、鉴权）不能让 AI 自己说改就改。
流程：
  1. AI 调 pc.self_update 想改底线文件 → 自动生成一条待确认请求，返回 consent_id
  2. 用户在**本机后台看板**点「同意」或「拒绝」（手机 AI 进不来这个页面）
  3. AI 用 consent_id 重试，检查状态；同意了才放行

关键点：**AI 没有任何接口能自己 approve**。approve 只在本机回环的接口里开放。
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
import threading
import time

from .paths import DATA_DIR

logger = logging.getLogger("pccore.consent")

DB_FILE = DATA_DIR / "consent.db"
_lock = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,           -- self_update / delete / payment / other
    target      TEXT NOT NULL,           -- 涉及的文件/对象
    detail      TEXT NOT NULL DEFAULT '',-- 人看的说明
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/approved/denied/expired
    created_ms  INTEGER NOT NULL,
    decided_ms  INTEGER NOT NULL DEFAULT 0,
    decided_by  TEXT NOT NULL DEFAULT '',
    used_ms     INTEGER NOT NULL DEFAULT 0       -- 已被消费的时间（一次性）
);
CREATE INDEX IF NOT EXISTS idx_cstatus ON requests(status, created_ms);
"""

DEFAULT_TTL_MS = 30 * 60 * 1000   # 30 分钟内有效


def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_FILE), timeout=30.0, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
    except Exception:  # noqa: BLE001
        pass
    return c


def init() -> None:
    try:
        with _lock, _conn() as c:
            c.executescript(_SCHEMA)
    except Exception:  # noqa: BLE001
        logger.exception("确认库建表失败")


def create(kind: str, target: str, detail: str = "") -> dict:
    """AI 发起一条待确认请求，返回 id（AI 拿不到「批准」的权限）。"""
    init()
    cid = "c_" + secrets.token_hex(8)
    ts = int(time.time() * 1000)
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO requests(id,kind,target,detail,status,created_ms) VALUES(?,?,?,?,'pending',?)",
            (cid, (kind or "other")[:24], (target or "")[:200], (detail or "")[:1000], ts),
        )
    logger.info("待确认 #%s [%s] %s", cid, kind, target)
    # 1) 电脑上弹系统通知
    try:
        from . import notify  # noqa: PLC0415

        notify.notify_consent(target, detail)
    except Exception:  # noqa: BLE001
        pass
    # 2) 推到主动消息通道（手机 App 会弹出来，第一时间知道）
    try:
        from . import proactive  # noqa: PLC0415

        proactive.push(
            f"有件事等你点头：{target}。{detail[:120]}\n去控制台（:8771）点同意或拒绝。",
            kind="alert", source="consent", priority=3,
        )
    except Exception:  # noqa: BLE001
        pass
    return {"id": cid, "kind": kind, "target": target, "detail": detail, "status": "pending"}


def get(cid: str) -> dict | None:
    init()
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM requests WHERE id=?", (cid,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    if d["status"] == "pending" and (int(time.time() * 1000) - int(d["created_ms"])) > DEFAULT_TTL_MS:
        d["status"] = "expired"
    return d


def pending() -> list[dict]:
    init()
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM requests WHERE status='pending' ORDER BY created_ms DESC LIMIT 30"
        ).fetchall()
    now = int(time.time() * 1000)
    out = []
    for r in rows:
        d = dict(r)
        if (now - int(d["created_ms"])) > DEFAULT_TTL_MS:
            continue
        out.append(d)
    return out


def approve(cid: str, by: str = "user") -> bool:
    """只能由本机后台调用（接口层做了回环限制）。"""
    init()
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE requests SET status='approved', decided_ms=?, decided_by=? "
            "WHERE id=? AND status='pending'",
            (int(time.time() * 1000), by[:32], cid),
        )
        ok = cur.rowcount > 0
    if ok:
        logger.info("已批准 #%s by %s", cid, by)
    return ok


def deny(cid: str, by: str = "user") -> bool:
    init()
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE requests SET status='denied', decided_ms=?, decided_by=? "
            "WHERE id=? AND status='pending'",
            (int(time.time() * 1000), by[:32], cid),
        )
        ok = cur.rowcount > 0
    if ok:
        logger.info("已拒绝 #%s by %s", cid, by)
    return ok


def consume(cid: str) -> tuple[bool, str]:
    """AI 用请求：只有 approved 且没用过才放行，用一次就作废。"""
    init()
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM requests WHERE id=?", (cid,)).fetchone()
        if r is None:
            return False, "没有这条确认请求"
        d = dict(r)
        if d["status"] == "pending":
            return False, "还在等你确认（去本机后台看板点同意）"
        if d["status"] == "denied":
            return False, "你已经拒绝了这次修改"
        if d["status"] == "expired":
            return False, "确认过期了，重新发起一次"
        if int(d["used_ms"]) > 0:
            return False, "这条确认已经用过了，不能重复用"
        if d["status"] != "approved":
            return False, f"状态不对：{d['status']}"
        c.execute("UPDATE requests SET used_ms=? WHERE id=?", (int(time.time() * 1000), cid))
    return True, "已确认"


def state() -> dict:
    init()
    with _lock, _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM requests").fetchone()["n"]
        pend = c.execute("SELECT COUNT(*) AS n FROM requests WHERE status='pending'").fetchone()["n"]
    return {"total": int(total), "pending": int(pend)}
