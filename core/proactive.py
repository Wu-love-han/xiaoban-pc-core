"""主动消息通道——让小伴能主动开口，而不是只能等用户说话。

小伴的需求：「现在我只能被动等用户开口，希望有主动触发的通道：定时提醒、
察觉到某件事时主动开口（电脑资源告急、有通知进来）」

设计：
- 消息先落到 data/proactive.db 的队列里（离线也不丢）
- 前端每 20 秒拉一次未读，显示成聊天气泡
- 任何模块都能 push：autopilot 定时、资源监控、手机通知转发
- 同一条消息不会重复弹（ack 之后才消失）
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time

from .paths import DATA_DIR

logger = logging.getLogger("pccore.proactive")

DB_FILE = DATA_DIR / "proactive.db"
_lock = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    text      TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'note',   -- reminder/alert/notice/note
    source    TEXT NOT NULL DEFAULT '',       -- autopilot/monitor/phone/manual
    priority  INTEGER NOT NULL DEFAULT 1,     -- 1 普通 2 重要 3 紧急
    ts_ms     INTEGER NOT NULL,
    ack_ms    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ack ON messages(ack_ms, id);
"""


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
        logger.exception("主动消息库建表失败")


def push(text: str, kind: str = "note", source: str = "manual", priority: int = 1) -> int:
    """塞一条主动消息进队列，返回 id。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("消息内容不能为空")
    init()
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO messages(text,kind,source,priority,ts_ms) VALUES(?,?,?,?,?)",
            (text[:1000], (kind or "note")[:16], (source or "")[:24], int(priority), int(time.time() * 1000)),
        )
        mid = int(cur.lastrowid)
    logger.info("主动消息入队 #%s [%s] %s", mid, kind, text[:60])
    # 同时弹系统通知，人在别的软件上也能看到
    try:
        from . import notify  # noqa: PLC0415

        notify.notify_proactive(text, kind)
    except Exception:  # noqa: BLE001
        pass
    return mid


def pending(limit: int = 10) -> list[dict]:
    """还没被前端确认的消息。"""
    init()
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM messages WHERE ack_ms=0 ORDER BY priority DESC, id ASC LIMIT ?",
            (max(1, min(50, int(limit))),),
        ).fetchall()
    return [dict(r) for r in rows]


def ack(mid: int) -> bool:
    init()
    with _lock, _conn() as c:
        cur = c.execute("UPDATE messages SET ack_ms=? WHERE id=? AND ack_ms=0",
                        (int(time.time() * 1000), int(mid)))
        return cur.rowcount > 0


def ack_all() -> int:
    init()
    with _lock, _conn() as c:
        cur = c.execute("UPDATE messages SET ack_ms=? WHERE ack_ms=0", (int(time.time() * 1000),))
        return cur.rowcount


def recent(limit: int = 30) -> list[dict]:
    init()
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM messages ORDER BY id DESC LIMIT ?",
                         (max(1, min(100, int(limit))),)).fetchall()
    return [dict(r) for r in rows]


def state() -> dict:
    init()
    with _lock, _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
        pend = c.execute("SELECT COUNT(*) AS n FROM messages WHERE ack_ms=0").fetchone()["n"]
    return {"total": int(total), "pending": int(pend)}


# ---------------------------------------------------------------- 自动触发

_alert_state: dict[str, float] = {}   # 同类告警的冷却（避免刷屏）


def _cooled(key: str, cooldown_s: int) -> bool:
    now = time.time()
    last = _alert_state.get(key, 0.0)
    if now - last < cooldown_s:
        return False
    _alert_state[key] = now
    return True


def check_resources() -> str:
    """看电脑资源，紧张就主动提醒（带冷却，不会刷屏）。"""
    try:
        import psutil  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return ""

    try:
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.5)
        disk = psutil.disk_usage("C:\\")
    except Exception:  # noqa: BLE001
        return ""

    msgs = []
    if mem.percent >= 90 and _cooled("mem", 1800):
        msgs.append(f"内存快满了（{mem.percent:.0f}%），还剩 {mem.available / 1024**3:.1f}G。要不要我帮你看看谁在吃内存？")
    if cpu >= 90 and _cooled("cpu", 1800):
        msgs.append(f"CPU 跑到 {cpu:.0f}% 了，机器有点吃力。")
    if disk.percent >= 90 and _cooled("disk", 3600):
        msgs.append(f"C 盘只剩 {disk.free / 1024**3:.1f}G 了（已用 {disk.percent:.0f}%）。")

    for m in msgs:
        push(m, kind="alert", source="monitor", priority=2)
    return "；".join(msgs)
