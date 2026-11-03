"""主动行为调度引擎：让小伴「自己找事做」。

设计目标：小伴不能只会被动回话，还要能主动找用户。这里不搞 asyncio、
不引 cron 库，就用一个 daemon 线程 + 一张行为表，每隔一段时间（默认 60 秒）
检查有没有到期行为，到期就把它要说的消息塞进「待发送队列」，前端或聊天接口
来取走。

行为是「触发条件 → 动作」的规则，先做四种：

- greeting  问候：用户长时间没来（默认 2 小时），主动发一条问候
- time      时间提醒：整点（at 为空）或每天特定时间（at="23:00" 提醒休息）
- recall    记忆回想：随机翻一条长期记忆，生成「想起你之前说…」的主动消息
- custom    自定义：手动加一条定时消息 {"at": "23:30", "text": "该睡觉啦"}

触发条件只用 datetime 字符串比较（"YYYY-MM-DD HH:MM" 按字典序比大小），
不引入任何第三方调度库。数据落在独立的 data/autopilot.db，不污染主库。
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Iterable

from . import config as cfg_mod
from . import db as core_db
from .paths import DATA_DIR, ensure_dirs

logger = logging.getLogger("pccore.autopilot")

# 独立库文件。主库 pccore.db 归 core.db 管，这里互不干扰。
DB_FILE = DATA_DIR / "autopilot.db"

# 默认节奏（config.json 的 autopilot 段可以覆盖，没配就用这些）。
DEFAULT_CHECK_SECONDS = 60           # 默认每 60 秒检查一次
DEFAULT_GREETING_IDLE_MINUTES = 120  # 默认 2 小时没来就问候
DEFAULT_RECALL_INTERVAL_MINUTES = 60  # 记忆回想的基础间隔

KINDS = ("greeting", "time", "recall", "custom")

_local = threading.local()
_write_lock = threading.RLock()
_inited = False
_init_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS behaviors (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT NOT NULL,
    at               TEXT NOT NULL DEFAULT '',
    text             TEXT NOT NULL DEFAULT '',
    interval_minutes INTEGER NOT NULL DEFAULT 0,
    enabled          INTEGER NOT NULL DEFAULT 1,
    next_due         TEXT NOT NULL DEFAULT '',
    last_fired       TEXT NOT NULL DEFAULT '',
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_behaviors_enabled ON behaviors(enabled, kind);

CREATE TABLE IF NOT EXISTS queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    behavior_id INTEGER NOT NULL DEFAULT 0,
    kind        TEXT NOT NULL,
    text        TEXT NOT NULL DEFAULT '',
    meta        TEXT NOT NULL DEFAULT '{}',
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_queue_created ON queue(created_at);

CREATE TABLE IF NOT EXISTS sent (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    behavior_id INTEGER NOT NULL DEFAULT 0,
    kind        TEXT NOT NULL,
    text        TEXT NOT NULL DEFAULT '',
    sent_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sent_sent_at ON sent(sent_at);
"""


# ---------------------------------------------------------------- 基础

def now_ms() -> int:
    return int(time.time() * 1000)


def _now_dt() -> datetime:
    return datetime.now()


def _min_str(dt: datetime) -> str:
    """分钟粒度的可比字符串：'YYYY-MM-DD HH:MM'。"""
    return dt.strftime("%Y-%m-%d %H:%M")


def _loads(s: Any, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


def conn() -> sqlite3.Connection:
    """取当前线程的连接（懒建）。sqlite3 连接不能跨线程，和 core.db 一个道理。"""
    c = getattr(_local, "conn", None)
    if c is None:
        ensure_dirs()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_FILE), timeout=30.0, isolation_level=None, check_same_thread=False)
        # 抗并发：WAL + 忙等，避免多线程同时写导致底层崩溃
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
    """建表。幂等，进程内只跑一次。"""
    global _inited
    c = conn()
    with _write_lock:
        c.executescript(SCHEMA)
    _inited = True


def _ensure_init() -> None:
    global _inited
    if _inited:
        return
    with _init_lock:
        if not _inited:
            init()


def _write(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    c = conn()
    with _write_lock:
        return c.execute(sql, tuple(params))


def _query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return list(conn().execute(sql, tuple(params)).fetchall())


def _query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return conn().execute(sql, tuple(params)).fetchone()


# ---------------------------------------------------------------- 配置兜底

def _check_seconds() -> int:
    try:
        v = int(cfg_mod.get("autopilot.interval_seconds") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v >= 5 else DEFAULT_CHECK_SECONDS


def _idle_minutes() -> int:
    try:
        v = int(cfg_mod.get("autopilot.greeting_idle_minutes") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else DEFAULT_GREETING_IDLE_MINUTES


def _recall_interval_minutes() -> int:
    try:
        v = int(cfg_mod.get("autopilot.recall_interval_minutes") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else DEFAULT_RECALL_INTERVAL_MINUTES


# ---------------------------------------------------------------- 时间解析

def parse_at(raw: str) -> str:
    """把 'HH:MM' / 'H:MM' 归一成 'HH:MM'；不合法抛 ValueError。"""
    s = (raw or "").strip()
    if not s:
        return ""
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(f"时间格式不对：{raw!r}（要 HH:MM 这种）")
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"时间格式不对：{raw!r}（要 HH:MM 这种）") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"时间超出范围：{raw!r}（时 0-23，分 0-59）")
    return f"{h:02d}:{m:02d}"


def _next_daily_due(hhmm: str, after: datetime) -> str:
    """下一次 hhmm 时刻（严格晚于 after）。"""
    h, m = (int(x) for x in hhmm.split(":"))
    cand = after.replace(hour=h, minute=m, second=0, microsecond=0)
    if cand <= after:
        cand += timedelta(days=1)
    return _min_str(cand)


def _next_hourly_due(after: datetime) -> str:
    """下一个整点（:00）。"""
    cand = (after + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return _min_str(cand)


def _next_recall_due(after: datetime, interval_minutes: int) -> str:
    """回想的下一次到期时间：基础间隔上下浮动一半，最少 15 分钟。"""
    base = interval_minutes if interval_minutes > 0 else _recall_interval_minutes()
    half = max(1, base // 2)
    mins = max(15, base + random.randint(-half, half))
    return _min_str(after + timedelta(minutes=mins))


# ---------------------------------------------------------------- 行为 CRUD

def _row_to_behavior(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["enabled"] = bool(d.get("enabled"))
    return d


def list_behaviors() -> list[dict]:
    _ensure_init()
    rows = _query("SELECT * FROM behaviors ORDER BY id")
    return [_row_to_behavior(r) for r in rows]


def count_behaviors() -> int:
    _ensure_init()
    r = _query_one("SELECT COUNT(*) AS c FROM behaviors")
    return int(r["c"]) if r else 0


def get_behavior(bid: int) -> dict | None:
    _ensure_init()
    r = _query_one("SELECT * FROM behaviors WHERE id=?", (bid,))
    return _row_to_behavior(r) if r else None


def add_behavior(kind: str, at: str = "", text: str = "", interval_minutes: int = 0) -> dict:
    """新增一条行为规则。kind 不合法 / at 格式不对时抛 ValueError。"""
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"不认识的行为类型：{kind!r}（可选 {', '.join(KINDS)}）")

    interval = int(interval_minutes or 0)
    if interval < 0:
        raise ValueError("interval_minutes 不能是负数")

    at_norm = ""
    if kind in ("custom", "time"):
        at_norm = parse_at(at)
        if kind == "custom" and not at_norm:
            raise ValueError("custom 行为需要给 at（例如 23:30）")

    now = _now_dt()
    now_min = _min_str(now)

    # 首次到期时间：定时类立刻算出下一次；问候按需算；回想随机排期。
    if kind in ("custom", "time"):
        next_due = _next_daily_due(at_norm, now) if at_norm else _next_hourly_due(now)
    elif kind == "recall":
        next_due = _next_recall_due(now, interval)
    else:  # greeting 没有固定排期，每次检查现算
        next_due = ""

    _ensure_init()
    ts = now_ms()
    cur = _write(
        """INSERT INTO behaviors(kind,at,text,interval_minutes,enabled,next_due,last_fired,created_at,updated_at)
           VALUES(?,?,?,?,1,?, '', ?, ?)""",
        (kind, at_norm, (text or "").strip(), interval, next_due, ts, ts),
    )
    return {
        "id": int(cur.lastrowid or 0),
        "kind": kind,
        "at": at_norm,
        "text": (text or "").strip(),
        "interval_minutes": interval,
        "enabled": True,
        "next_due": next_due,
        "last_fired": "",
        "created_at": ts,
        "updated_at": ts,
    }


def delete_behavior(bid: int) -> bool:
    _ensure_init()
    cur = _write("DELETE FROM behaviors WHERE id=?", (bid,))
    return cur.rowcount > 0


def _set_next_due(bid: int, due: str) -> None:
    _write("UPDATE behaviors SET next_due=?, updated_at=? WHERE id=?", (due, now_ms(), bid))


def _mark_fired(bid: int, fired_min: str) -> None:
    _write("UPDATE behaviors SET last_fired=?, updated_at=? WHERE id=?", (fired_min, now_ms(), bid))


# ---------------------------------------------------------------- 待发送队列

def enqueue(behavior_id: int, kind: str, text: str, meta: dict | None = None) -> dict:
    """把一条主动消息放进待发送队列，等前端/聊天接口取走。"""
    _ensure_init()
    ts = now_ms()
    cur = _write(
        "INSERT INTO queue(behavior_id,kind,text,meta,created_at) VALUES(?,?,?,?,?)",
        (
            int(behavior_id or 0),
            kind,
            (text or "").strip(),
            json.dumps(meta or {}, ensure_ascii=False),
            ts,
        ),
    )
    return {
        "id": int(cur.lastrowid or 0),
        "behavior_id": int(behavior_id or 0),
        "kind": kind,
        "text": (text or "").strip(),
        "meta": meta or {},
        "created_at": ts,
    }


def list_queue() -> list[dict]:
    _ensure_init()
    rows = _query("SELECT * FROM queue ORDER BY id")
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = _loads(d.get("meta"), {})
        out.append(d)
    return out


def queue_len() -> int:
    _ensure_init()
    r = _query_one("SELECT COUNT(*) AS c FROM queue")
    return int(r["c"]) if r else 0


def count_sent() -> int:
    _ensure_init()
    r = _query_one("SELECT COUNT(*) AS c FROM sent")
    return int(r["c"]) if r else 0


def drain_queue() -> list[dict]:
    """清空队列并返回被清掉的消息（供聊天接口用）。

    取走 = 已发送：顺手搬进 sent 表留个记录，别让「发过什么」无迹可查。
    """
    _ensure_init()
    with _write_lock:
        rows = _query("SELECT * FROM queue ORDER BY id")
        out = []
        for r in rows:
            d = dict(r)
            d["meta"] = _loads(d.get("meta"), {})
            out.append(d)
            _write(
                "INSERT INTO sent(behavior_id,kind,text,sent_at) VALUES(?,?,?,?)",
                (int(d.get("behavior_id") or 0), d.get("kind") or "", d.get("text") or "", now_ms()),
            )
        _write("DELETE FROM queue")
        return out


# ---------------------------------------------------------------- 触发判断

def _last_user_activity_ms() -> int | None:
    """用户最近一次说话的毫秒时间戳；从没说过话返回 None。

    读主库 messages 表（role='user'），不在这里另起炉灶。
    主库还没初始化时会抛异常，返回 None 让问候跳过，绝不影响调度循环。
    """
    try:
        row = core_db.query_one("SELECT MAX(created_at) AS ts FROM messages WHERE role='user'")
    except Exception:  # noqa: BLE001
        logger.warning("读用户活跃时间失败（主库可能还没建好），本轮跳过问候", exc_info=True)
        return None
    if row is None or row["ts"] is None:
        return None
    return int(row["ts"])


def _pick_memory() -> dict | None:
    """随机翻一条长期记忆。没有记忆返回 None。"""
    try:
        row = core_db.query_one("SELECT id,key,value FROM memories ORDER BY RANDOM() LIMIT 1")
    except Exception:  # noqa: BLE001
        logger.warning("翻长期记忆失败（主库可能还没建好），本轮跳过回想", exc_info=True)
        return None
    return dict(row) if row is not None else None


def _check_behavior(r: sqlite3.Row, now_dt: datetime, now_min: str) -> int:
    """检查单条行为，到期就入队。返回 0/1（触发了几条）。"""
    kind = r["kind"]
    due = (r["next_due"] or "").strip()

    # ---- 定时类（time / custom）：next_due 到期就发
    if kind in ("time", "custom"):
        if not due or due > now_min:
            return 0
        text = (r["text"] or "").strip() or "（时间提醒）"
        enqueue(r["id"], kind, text)
        _mark_fired(r["id"], now_min)
        at = (r["at"] or "").strip()
        _set_next_due(r["id"], _next_daily_due(at, now_dt) if at else _next_hourly_due(now_dt))
        return 1

    # ---- 问候：用户 idle 超过阈值，且上次问候发生在用户最近活跃之前
    if kind == "greeting":
        threshold = int(r["interval_minutes"] or 0) or _idle_minutes()
        last_ms = _last_user_activity_ms()
        if last_ms is None:
            return 0
        idle_min = (now_ms() - last_ms) / 60000.0
        if idle_min < threshold:
            return 0
        last_fired = (r["last_fired"] or "").strip()
        last_active_min = _min_str(datetime.fromtimestamp(last_ms / 1000.0))
        if last_fired and last_fired >= last_active_min:
            return 0  # 这一轮 idle 已经问候过了，别再刷屏
        text = (r["text"] or "").strip() or "在吗？好久没看到你啦，我一直都在～"
        enqueue(r["id"], "greeting", text)
        _mark_fired(r["id"], now_min)
        return 1

    # ---- 回想：next_due 到期翻一条记忆
    if kind == "recall":
        if not due or due > now_min:
            return 0
        mem = _pick_memory()
        if mem is None:
            _set_next_due(r["id"], _next_recall_due(now_dt, int(r["interval_minutes"] or 0)))
            return 0
        value = str(mem.get("value") or "").strip() or str(mem.get("key") or "").strip()
        if not value:
            _set_next_due(r["id"], _next_recall_due(now_dt, int(r["interval_minutes"] or 0)))
            return 0
        template = (r["text"] or "").strip() or "想起你之前说：{memory}"
        text = template.replace("{memory}", value)
        enqueue(
            r["id"],
            "recall",
            text,
            meta={"memory_id": mem.get("id"), "memory_key": mem.get("key", "")},
        )
        _mark_fired(r["id"], now_min)
        _set_next_due(r["id"], _next_recall_due(now_dt, int(r["interval_minutes"] or 0)))
        return 1

    return 0


def tick_once() -> dict:
    """检查一轮所有启用的行为，返回这轮干了什么（供线程和测试用）。

    同时做两件主动的事：
      1. 把触发到的行为转成「主动消息」推给前端（小伴主动开口）
      2. 看一眼资源，紧张就提醒
    """
    _ensure_init()
    now_dt = _now_dt()
    now_min = _min_str(now_dt)
    fired = 0
    rows = _query("SELECT * FROM behaviors WHERE enabled=1 ORDER BY id")
    for r in rows:
        try:
            fired += _check_behavior(r, now_dt, now_min)
        except Exception:  # noqa: BLE001 - 一条行为坏掉不能拖垮整轮检查
            logger.exception("行为 %s 检查出错，跳过", r["id"])

    # 队列里的消息 → 主动消息通道（让前端能弹出来）
    try:
        from . import proactive  # noqa: PLC0415

        for m in drain_queue():
            proactive.push(
                m.get("text") or "",
                kind="reminder",
                source="autopilot",
                priority=2 if m.get("kind") in ("time", "greeting") else 1,
            )
    except Exception:  # noqa: BLE001
        logger.warning("转主动消息失败", exc_info=True)

    # 资源告急主动提醒
    try:
        from . import proactive  # noqa: PLC0415

        proactive.check_resources()
    except Exception:  # noqa: BLE001
        logger.debug("资源检查失败", exc_info=True)

    return {"checked_at": now_min, "checked": len(rows), "fired": fired}


# ---------------------------------------------------------------- 后台线程

class _Scheduler:
    """daemon 线程壳：跑 tick_once，用一个 Event 支持「加了新行为马上醒」。"""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._guard = threading.Lock()
        self._next_check_at = 0.0

    def start(self) -> bool:
        """起线程（幂等）。返回是否新起了一个。"""
        with self._guard:
            if self._thread is not None and self._thread.is_alive():
                return False
            _ensure_init()
            self._stop.clear()
            t = threading.Thread(target=self._loop, name="autopilot", daemon=True)
            self._thread = t
            t.start()
            return True

    def _loop(self) -> None:
        logger.info("主动行为调度线程启动，每 %d 秒检查一次", _check_seconds())
        while not self._stop.is_set():
            try:
                tick_once()
            except Exception:  # noqa: BLE001
                logger.exception("主动行为检查出错")
            self._next_check_at = time.time() + _check_seconds()
            self._wake.wait(timeout=_check_seconds())
            self._wake.clear()
        logger.info("主动行为调度线程退出")

    def wake(self) -> None:
        self._wake.set()

    def running(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())

    def next_check_at(self) -> float:
        return self._next_check_at

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()


_scheduler = _Scheduler()


def ensure_running() -> bool:
    """保证后台线程在跑（懒启动：第一次有人问状态/加行为时才起）。"""
    try:
        _scheduler.start()
    except Exception:  # noqa: BLE001
        logger.exception("启动主动行为调度失败")
    return _scheduler.running()


def is_running() -> bool:
    return _scheduler.running()


def wake() -> None:
    """加了新行为后捅一下线程，别等到下一轮 60 秒。"""
    _scheduler.wake()


def status() -> dict:
    """调度器状态快照，给 GET /api/autopilot/status。"""
    ensure_running()
    nxt = _scheduler.next_check_at()
    return {
        "running": _scheduler.running(),
        "behaviors": count_behaviors(),
        "queue": queue_len(),
        "sent_total": count_sent(),
        "check_seconds": _check_seconds(),
        "next_check_at": (
            datetime.fromtimestamp(nxt).strftime("%Y-%m-%d %H:%M:%S") if nxt else ""
        ),
        "db_file": str(DB_FILE),
    }
