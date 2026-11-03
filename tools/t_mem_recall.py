"""mem.recall：按关键词 / 时间 / 场景召回记忆。

小伴的需求：「记忆支持按时间、按场景检索，而不只是关键词匹配」
- query：关键词（老行为不变）
- since / until：时间范围，支持「3天前」「上周」「2026-10-01」这类说法
- category：按分类（场景）过滤，比如「用户自述」「偏好」「工作」
"""

from __future__ import annotations

import time
from typing import Any

from . import _common as C


def _parse_time(raw: str) -> int:
    """把「3天前」「上周」「2026-10-01」换成毫秒时间戳；认不出返回 0。"""
    s = (raw or "").strip()
    if not s:
        return 0
    now = time.time()
    # 相对说法
    units = {"分钟": 60, "小时": 3600, "天": 86400, "周": 604800, "月": 2592000, "年": 31536000}
    import re

    m = re.match(r"(\d+)\s*(分钟|小时|天|周|月|年)前?$", s)
    if m:
        return int((now - int(m.group(1)) * units[m.group(2)]) * 1000)
    if s in ("昨天",):
        return int((now - 86400) * 1000)
    if s in ("上周",):
        return int((now - 604800) * 1000)
    if s in ("上个月", "上月"):
        return int((now - 2592000) * 1000)
    if s in ("今天",):
        lt = time.localtime()
        start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        return int(start * 1000)
    # 绝对日期
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return int(time.mktime(time.strptime(s, fmt)) * 1000)
        except ValueError:
            continue
    return 0


def run(args: dict, ctx: Any) -> dict:
    if not bool(C.cfg_get(ctx, "memory.enabled", True)):
        return C.fail("配置里把记忆功能关掉了（memory.enabled = false）。", "MemoryDisabled")

    query = str(args.get("query") or args.get("key") or args.get("q") or "").strip()
    category = str(args.get("category") or args.get("scene") or "").strip()
    since_ms = _parse_time(str(args.get("since") or ""))
    until_ms = _parse_time(str(args.get("until") or ""))

    try:
        limit = int(args.get("limit") or C.cfg_get(ctx, "memory.max_inject", 6) or 6)
    except (TypeError, ValueError):
        limit = 6
    limit = max(1, min(limit, 20))

    rows = []
    try:
        C.ensure_db()
        from core import memory_engine  # noqa: PLC0415

        memory_engine.init()
        rows = memory_engine.recall_long_term(
            query_text=query, limit=limit,
            since_ms=since_ms, until_ms=until_ms, category=category,
        )
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"翻记忆的时候出错了（{type(exc).__name__}）", f"{type(exc).__name__}: {exc}")

    # 分层记忆库没结果时，回落老的 KV 记忆表（兼容以前记的东西）
    if not rows and not (since_ms or until_ms or category):
        try:
            from core import db  # noqa: PLC0415

            for r in db.recall(query, scope="global", limit=limit):
                rows.append({
                    "id": None,
                    "content": f"{r.get('key')}：{r.get('value')}",
                    "category": "旧记忆",
                    "importance": float(r.get("weight") or 0),
                    "created_at": r.get("created_at"),
                    "recall_count": r.get("recall_count"),
                })
        except Exception:  # noqa: BLE001
            pass

    items = [
        {
            "id": r.get("id"),
            "content": str(r.get("content") or ""),
            "category": str(r.get("category") or ""),
            "importance": round(float(r.get("importance") or 0), 2),
            "created_at": r.get("created_at"),
            "recall_count": r.get("recall_count"),
        }
        for r in rows
    ]

    if not items:
        what = f"「{query}」" if query else "相关的事"
        scope_note = ""
        if category:
            scope_note = f"（场景：{category}）"
        if since_ms or until_ms:
            scope_note += "（限定时间范围）"
        return C.ok(f"关于{what}我这儿没记着什么{scope_note}。", query=query, items=[])

    lines = []
    for it in items:
        when = ""
        try:
            when = time.strftime("%m-%d", time.localtime((it["created_at"] or 0) / 1000)) + " "
        except Exception:  # noqa: BLE001
            pass
        lines.append(f"- [{it['id']}] {when}{it['content']}（{it['category']}，重要度 {it['importance']}）")

    head = f"想起 {len(items)} 条" + (f"关于「{query}」的" if query else "")
    if category:
        head += f"（场景：{category}）"
    return C.ok(f"{head}：\n" + "\n".join(lines), query=query, items=items)


TOOL = {
    "name": "mem.recall",
    "title": "想起一件事",
    "desc": (
        "翻长期记忆。可以按关键词、按时间、按场景查。"
        "since/until 支持「3天前」「上周」「2026-10-01」这类说法；category 按分类过滤。"
        "返回带记忆 id，配合 mem.update / mem.forget 可以改或删。"
    ),
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "关键词；省略则按重要度列出"},
            "since": {"type": "string", "description": "起始时间，如「3天前」「上周」「2026-10-01」"},
            "until": {"type": "string", "description": "截止时间，同上"},
            "category": {"type": "string", "description": "按场景/分类过滤，如「用户自述」"},
            "limit": {"type": "integer", "description": "最多几条（1-20）"},
        },
        "required": [],
    },
    "run": C.guard(run),
}
