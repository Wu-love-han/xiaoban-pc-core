"""分层记忆 + 情绪引擎（小伴的「活人感」核心）。

设计取舍：
- **短期记忆** 存最近 N 轮对话摘要（N 由参数/配置决定，默认 20）。存 SQLite
  `short_term_summaries` 表，只保留最近 N 条，超出的自动挤掉。
- **长期记忆** 存关键事实（用户说过的重要事、喜好、约定）。`long_term_memories`
  表带 `importance(0-1)`、`recall_count`、`last_recalled_at`，供后续按重要性召回。
- **印象/好感** 存 `impressions`（一句话一条）+ `affinity`（0-100）好感度数值，
  随对话更新。
- **情绪状态** 是单行可读对象：mood / energy(0-100) / last_updated。
  提供 `decay()`：随时间把 energy 向基线缓慢回落，mood 随之校准。

和 `core/db.py` 的关系：memory.db 与主库分开，因为「长期记忆」可能被频繁写入
（每次对话都可能提取事实），单独一个库文件，坏了可以直接删掉重建而不影响会话。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from typing import Any, Iterable

from .paths import DATA_DIR, ensure_dirs

logger = logging.getLogger("pccore.memory")

# ------------------------------------------------------------------ 常量
DB_FILE = DATA_DIR / "memory.db"

# 情绪基线：energy 最终会朝这个值缓慢回落，模拟「累了想歇、闲了回神」。
ENERGY_BASELINE = 65.0
# 每分钟 energy 向基线回落的幅度（点数）。
DECAY_PER_MINUTE = 1.5
# 好感度 / energy 越界保护。
AFFINITY_MIN, AFFINITY_MAX = 0, 100
ENERGY_MIN, ENERGY_MAX = 0, 100

SHORT_TERM_DEFAULT = 20

# 合法 mood 白名单，防脏数据。不在名单里的 mood 会被归到 calm。
MOODS = ("calm", "happy", "tired", "curious", "excited", "sad", "anxious", "focused")

_local = threading.local()
_write_lock = threading.RLock()


def _now_ms() -> int:
    """毫秒时间戳。独立实现，不依赖 core.db。"""
    return int(time.time() * 1000)


# ---------------------------------------------------------------- 表结构
SCHEMA = """
CREATE TABLE IF NOT EXISTS short_term_summaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    role        TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sts_created ON short_term_summaries(id, created_at);

CREATE TABLE IF NOT EXISTS long_term_memories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content         TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT '通用',
    importance      REAL NOT NULL DEFAULT 0.5,
    created_at      INTEGER NOT NULL,
    last_recalled_at INTEGER NOT NULL DEFAULT 0,
    recall_count    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ltm_category ON long_term_memories(category, importance DESC);

CREATE TABLE IF NOT EXISTS impressions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);

-- 情绪状态单行表（id 固定为 1），避免并发写多行。
CREATE TABLE IF NOT EXISTS mood_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    mood        TEXT NOT NULL DEFAULT 'calm',
    energy      INTEGER NOT NULL DEFAULT 65,
    last_updated INTEGER NOT NULL
);

-- 通用键值表，好感度存在这里。
CREATE TABLE IF NOT EXISTS kv_store (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL DEFAULT '',
    updated_at  INTEGER NOT NULL DEFAULT 0
);
"""


# ---------------------------------------------------------------- 连接
def _conn() -> sqlite3.Connection:
    """取当前线程的连接（懒建，线程私有）。"""
    c = getattr(_local, "conn", None)
    if c is None:
        try:
            ensure_dirs()
        except Exception:  # noqa: BLE001
            logger.exception("确保数据目录失败")
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
    """建表（幂等）。启动时调用，失败不阻塞。"""
    try:
        with _write_lock:
            _conn().executescript(SCHEMA)
    except Exception:  # noqa: BLE001
        logger.exception("memory.db 初始化失败")


def _write(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    """写操作（串行化，避免 database is locked）。"""
    with _write_lock:
        return _conn().execute(sql, tuple(params))


def _query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return list(_conn().execute(sql, tuple(params)).fetchall())


def _query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return _conn().execute(sql, tuple(params)).fetchone()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _normalize_importance(v: Any, default: float = 0.5) -> float:
    """importance 归一化到 [0, 1]，非法输入回退默认值。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return _clamp(f, 0.0, 1.0)


def _normalize_energy(v: Any, default: float = 50.0) -> int:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return int(default)
    return int(round(_clamp(f, ENERGY_MIN, ENERGY_MAX)))


def _normalize_affinity(v: Any, default: float = 50.0) -> int:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return int(default)
    return int(round(_clamp(f, AFFINITY_MIN, AFFINITY_MAX)))


def _normalize_mood(v: Any) -> str:
    """非法 mood 一律归到 calm，防止前端乱填。"""
    s = str(v or "").strip().lower()
    return s if s in MOODS else "calm"


def _count(table: str) -> int:
    try:
        row = _query_one(f"SELECT COUNT(*) AS c FROM {table}")
        return int(row["c"]) if row else 0
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------- 短期记忆
def add_short_term(role: str, content: str, max_items: int | None = None) -> int:
    """追加一条短期记忆（对话摘要），只保留最近 `max_items` 条。返回当前条数。"""
    cap = max(1, int(max_items or SHORT_TERM_DEFAULT))
    try:
        _write(
            "INSERT INTO short_term_summaries(role,content,created_at) VALUES(?,?,?)",
            (str(role or "summary")[:20], str(content or ""), _now_ms()),
        )
        # 挤掉最旧的，只留最近 cap 条。
        _write(
            "DELETE FROM short_term_summaries WHERE id NOT IN "
            "(SELECT id FROM short_term_summaries ORDER BY id DESC LIMIT ?)",
            (cap,),
        )
        return _count("short_term_summaries")
    except Exception:  # noqa: BLE001
        logger.exception("写短期记忆失败")
        return _count("short_term_summaries")


def list_short_term(limit: int = 20) -> list[dict]:
    """按时间正序返回最近 `limit` 条短期记忆。"""
    try:
        rows = _query(
            "SELECT id,role,content,created_at FROM short_term_summaries "
            "ORDER BY id DESC LIMIT ?",
            (max(1, int(limit)),),
        )
        return [dict(r) for r in reversed(rows)]
    except Exception:  # noqa: BLE001
        logger.exception("读短期记忆失败")
        return []


# ---------------------------------------------------------------- 长期记忆
def remember_long_term(content: str, category: str = "通用", importance: Any = 0.5) -> dict:
    """手动/自动存一条长期记忆。返回完整行（含 id）。content 为空抛 ValueError。"""
    content = (content or "").strip()
    if not content:
        raise ValueError("content 不能为空")
    imp = _normalize_importance(importance)
    cat = (category or "通用").strip() or "通用"
    ts = _now_ms()
    cur = _write(
        "INSERT INTO long_term_memories(content,category,importance,created_at,last_recalled_at,recall_count) "
        "VALUES(?,?,?,?,0,0)",
        (content, cat, imp, ts),
    )
    return {
        "id": int(cur.lastrowid or 0),
        "content": content,
        "category": cat,
        "importance": imp,
        "created_at": ts,
        "last_recalled_at": 0,
        "recall_count": 0,
    }


def list_long_term(limit: int = 100) -> list[dict]:
    """长期记忆列表：重要度高的在前，其次最近召回过的。"""
    try:
        rows = _query(
            "SELECT * FROM long_term_memories "
            "ORDER BY importance DESC, last_recalled_at DESC, id DESC LIMIT ?",
            (max(1, int(limit)),),
        )
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        logger.exception("读长期记忆失败")
        return []


def recall_long_term(
    query_text: str = "",
    limit: int = 6,
    since_ms: int = 0,
    until_ms: int = 0,
    category: str = "",
) -> list[dict]:
    """召回长期记忆：有关键词做 LIKE 匹配，否则按重要度取 Top N。

    支持按时间范围（since_ms / until_ms）和分类（category）过滤——
    小伴的需求：「记忆支持按时间、按场景检索，而不只是关键词匹配」。

    召回会更新 last_recalled_at 与 recall_count（表示「被想起过一次」）。
    """
    q = (query_text or "").strip()
    limit = max(1, int(limit))
    since_ms = int(since_ms or 0)
    until_ms = int(until_ms or 0)
    category = (category or "").strip()

    # 时间 / 分类过滤片段
    extra_sql = ""
    extra_params: list[Any] = []
    if since_ms > 0:
        extra_sql += " AND created_at >= ?"
        extra_params.append(since_ms)
    if until_ms > 0:
        extra_sql += " AND created_at <= ?"
        extra_params.append(until_ms)
    if category:
        extra_sql += " AND category = ?"
        extra_params.append(category)

    try:
        if q:
            # 单字 + 双字滑窗，和 core.db.recall 的思路一致，不做向量。
            terms = {q}
            for i in range(len(q) - 1):
                terms.add(q[i : i + 2])
            # 单字也要进匹配（中文单字有意义，比如「喝」「累」「猫」）
            for ch in q:
                if ch.strip():
                    terms.add(ch)
            terms = [t for t in terms if t.strip()][:12]
            like = " OR ".join(["content LIKE ?"] * len(terms))
            params: list[Any] = [f"%{t}%" for t in terms]
            params.append(limit)
            params = params[:-1] + extra_params + [limit]
            rows = _query(
                f"SELECT * FROM long_term_memories WHERE ({like}){extra_sql} "
                f"ORDER BY importance DESC, last_recalled_at DESC, id DESC LIMIT ?",
                params,
            )
        else:
            where = ("WHERE 1=1" + extra_sql) if extra_sql else ""
            rows = _query(
                f"SELECT * FROM long_term_memories {where} "
                f"ORDER BY importance DESC, last_recalled_at DESC, id DESC LIMIT ?",
                extra_params + [limit],
            )
        out = [dict(r) for r in rows]
        ts = _now_ms()
        for d in out:
            _write(
                "UPDATE long_term_memories SET recall_count=recall_count+1, last_recalled_at=? WHERE id=?",
                (ts, d["id"]),
            )
            d["recall_count"] += 1
            d["last_recalled_at"] = ts
        return out
    except Exception:  # noqa: BLE001
        logger.exception("召回长期记忆失败")
        return []


def update_long_term(mem_id: int, content: str = "", category: str = "", importance: Any = None) -> bool:
    """更新一条长期记忆（内容/分类/重要度）。小伴的需求：记忆要能更新，不只增不减。"""
    sets, params = [], []
    if content.strip():
        sets.append("content=?")
        params.append(content.strip()[:500])
    if category.strip():
        sets.append("category=?")
        params.append(category.strip()[:32])
    if importance is not None:
        sets.append("importance=?")
        params.append(_normalize_importance(importance))
    if not sets:
        return False
    params.append(int(mem_id))
    try:
        cur = _write(f"UPDATE long_term_memories SET {', '.join(sets)} WHERE id=?", params)
        return cur.rowcount > 0
    except Exception:  # noqa: BLE001
        logger.exception("更新长期记忆失败")
        return False


def decay_long_term(older_than_days: int = 60, min_importance: float = 0.3) -> int:
    """遗忘：把很久没被想起、又不重要的记忆降权（不硬删）。

    小伴的需求：「记住的东西要能更新和遗忘，别只增不减」。
    """
    import time as _time

    cutoff = int((_time.time() - older_than_days * 86400) * 1000)
    try:
        cur = _write(
            "UPDATE long_term_memories SET importance = MAX(0.05, importance * 0.7) "
            "WHERE importance > ? AND last_recalled_at < ? AND created_at < ?",
            (min_importance, cutoff, cutoff),
        )
        return cur.rowcount
    except Exception:  # noqa: BLE001
        logger.exception("记忆降权失败")
        return 0


def forget_long_term(mem_id: int) -> bool:
    """删除一条长期记忆，返回是否真的删掉了。"""
    try:
        cur = _write("DELETE FROM long_term_memories WHERE id=?", (int(mem_id),))
        return cur.rowcount > 0
    except Exception:  # noqa: BLE001
        logger.exception("删除长期记忆失败")
        return False


# ---------------------------------------------------------------- 印象 / 好感
def add_impression(content: str) -> int | None:
    """追加一条对用户的印象。"""
    content = (content or "").strip()
    if not content:
        return None
    try:
        cur = _write(
            "INSERT INTO impressions(content,created_at) VALUES(?,?)",
            (content, _now_ms()),
        )
        return int(cur.lastrowid or 0)
    except Exception:  # noqa: BLE001
        logger.exception("写印象失败")
        return None


def list_impressions(limit: int = 50) -> list[dict]:
    try:
        rows = _query(
            "SELECT * FROM impressions ORDER BY id DESC LIMIT ?",
            (max(1, int(limit)),),
        )
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        logger.exception("读印象失败")
        return []


def get_affinity() -> int:
    """当前好感度（0-100）。没写过就用 50 的默认值。"""
    try:
        row = _query_one("SELECT value FROM kv_store WHERE key='affinity'")
        if row:
            return _normalize_affinity(row["value"], default=50.0)
        return 50
    except Exception:  # noqa: BLE001
        logger.exception("读好感度失败")
        return 50


def set_affinity(v: Any) -> int:
    """直接设好感度（测试/调试用），返回设置后的值。"""
    val = _normalize_affinity(v)
    try:
        _write(
            "INSERT INTO kv_store(key,value,updated_at) VALUES('affinity',?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (str(val), _now_ms()),
        )
        return val
    except Exception:  # noqa: BLE001
        logger.exception("设好感度失败")
        return val


def shift_affinity(delta: Any) -> int:
    """好感度加一个增量（可为负），越界自动截断。返回新值。"""
    try:
        d = float(delta)
    except (TypeError, ValueError):
        return get_affinity()
    new_val = int(round(_clamp(get_affinity() + d, AFFINITY_MIN, AFFINITY_MAX)))
    return set_affinity(new_val)


# ---------------------------------------------------------------- 情绪
def _default_mood() -> dict:
    return {
        "mood": "calm",
        "energy": int(ENERGY_BASELINE),
        "last_updated": _now_ms(),
    }


def _ensure_mood_row() -> None:
    """保证单行 mood_state 存在。"""
    row = _query_one("SELECT id FROM mood_state WHERE id=1")
    if not row:
        _write(
            "INSERT INTO mood_state(id,mood,energy,last_updated) VALUES(1,'calm',?,?)",
            (int(ENERGY_BASELINE), _now_ms()),
        )


def get_mood() -> dict:
    """当前情绪对象：mood / energy / last_updated。"""
    try:
        _ensure_mood_row()
        row = _query_one("SELECT * FROM mood_state WHERE id=1")
        if not row:
            return _default_mood()
        return {
            "mood": _normalize_mood(row["mood"]),
            "energy": _normalize_energy(row["energy"], default=ENERGY_BASELINE),
            "last_updated": int(row["last_updated"] or 0),
        }
    except Exception:  # noqa: BLE001
        logger.exception("读情绪失败")
        return _default_mood()


def set_mood(mood: str = "calm", energy: Any = 65) -> dict:
    """手动调情绪（调试/测试用）。mood 非法归 calm，energy 越界截断。"""
    try:
        m = _normalize_mood(mood)
        e = _normalize_energy(energy, default=ENERGY_BASELINE)
        _ensure_mood_row()
        ts = _now_ms()
        _write(
            "UPDATE mood_state SET mood=?, energy=?, last_updated=? WHERE id=1",
            (m, e, ts),
        )
        return {"mood": m, "energy": e, "last_updated": ts}
    except Exception:  # noqa: BLE001
        logger.exception("设情绪失败")
        return get_mood()


def update_mood(mood: str | None = None, energy: Any = None) -> dict:
    """程序侧更新：只传要改的字段。mood=None 表示不动 mood，energy=None 不动 energy。"""
    try:
        cur = get_mood()
        m = _normalize_mood(mood) if mood is not None else cur["mood"]
        e = _normalize_energy(energy, default=float(cur["energy"])) if energy is not None else cur["energy"]
        _ensure_mood_row()
        ts = _now_ms()
        _write(
            "UPDATE mood_state SET mood=?, energy=?, last_updated=? WHERE id=1",
            (m, e, ts),
        )
        return {"mood": m, "energy": e, "last_updated": ts}
    except Exception:  # noqa: BLE001
        logger.exception("更新情绪失败")
        return get_mood()


def decay_mood() -> dict:
    """情绪衰减：energy 按流逝分钟数向基线回落，并据此校准 mood。

    - energy > 基线：往下回落；energy < 基线：往上恢复。
    - energy 逼近基线（±2 点内）且 mood 是偏移态时，把 mood 归回 calm。
    """
    try:
        cur = get_mood()
        elapsed_min = max(0.0, (_now_ms() - int(cur.get("last_updated") or 0)) / 60000.0)
        if elapsed_min <= 0:
            return cur

        energy = float(cur["energy"])
        if energy > ENERGY_BASELINE:
            energy = max(ENERGY_BASELINE, energy - DECAY_PER_MINUTE * elapsed_min)
        elif energy < ENERGY_BASELINE:
            energy = min(ENERGY_BASELINE, energy + DECAY_PER_MINUTE * elapsed_min)
        energy = int(round(energy))

        mood = cur["mood"]
        if abs(energy - ENERGY_BASELINE) <= 2 and mood in ("tired", "excited", "anxious", "sad", "focused"):
            mood = "calm"

        _ensure_mood_row()
        ts = _now_ms()
        _write(
            "UPDATE mood_state SET mood=?, energy=?, last_updated=? WHERE id=1",
            (mood, energy, ts),
        )
        return {"mood": mood, "energy": energy, "last_updated": ts}
    except Exception:  # noqa: BLE001
        logger.exception("情绪衰减失败")
        return get_mood()


# ---------------------------------------------------------------- 总览
def get_state() -> dict:
    """当前记忆+情绪总览（给 /api/memory/state 用）。"""
    mood = decay_mood()
    try:
        short_term = list_short_term(limit=100)
        return {
            "short_term": {
                "count": len(short_term),
                "limit": SHORT_TERM_DEFAULT,
                "items": short_term,
            },
            "long_term": {
                "count": _count("long_term_memories"),
                "items": list_long_term(limit=100),
            },
            "impressions": list_impressions(limit=50),
            "affinity": get_affinity(),
            "mood": mood,
        }
    except Exception:  # noqa: BLE001
        logger.exception("聚合记忆总览失败")
        return {
            "short_term": {"count": 0, "limit": SHORT_TERM_DEFAULT, "items": []},
            "long_term": {"count": 0, "items": []},
            "impressions": [],
            "affinity": 50,
            "mood": mood,
        }


def self_check() -> bool:
    """供启动时/测试用：跑一遍建表+各函数，返回是否全部正常。"""
    try:
        init()
        get_mood()
        get_state()
        return True
    except Exception:  # noqa: BLE001
        logger.exception("记忆引擎自检失败")
        return False


__all__ = [
    "init", "self_check",
    "add_short_term", "list_short_term",
    "remember_long_term", "list_long_term", "recall_long_term", "forget_long_term",
    "add_impression", "list_impressions", "get_affinity", "set_affinity", "shift_affinity",
    "get_mood", "set_mood", "update_mood", "decay_mood",
    "get_state",
]
