"""每日总复盘（用户笔记："多段记忆总结 / 一天再一次"）。

思路：
- 每天固定时刻（默认 23:00）跑一次
- 把当天总志流水压缩成"长期要点"，写进总志的"三、长期要点"
- 同时更新情绪基线（睡一觉，精力恢复）
- 不删任何内容，只在"长期要点"区追加

复用 autopilot 的调度线程：注册一条 kind="custom" 的行为即可，
不需要另起线程。
"""

from __future__ import annotations

import logging
from datetime import datetime

from . import grand_log, memory_engine

logger = logging.getLogger("pccore.dailyreview")

REVIEW_TIME = "23:00"     # 每天复盘时刻
_MARK = "- （暂无）"


def run_once() -> str:
    """跑一次复盘，返回摘要文本。"""
    try:
        summary = grand_log.daily_compact()
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            mood = memory_engine.get_mood()
            # 睡一觉：精力回基线
            memory_engine.set_mood(mood="calm", energy=70)
            mood_note = f"情绪回到 calm/70（原 {mood.get('mood')}/{mood.get('energy')}）"
        except Exception:  # noqa: BLE001
            mood_note = "情绪未更新"

        text = grand_log.read()
        entry = f"- `{today}` 复盘：{summary}；{mood_note}"
        if "## 三、长期要点" in text:
            # 有占位符就替换占位符，否则追加到标题后
            if _MARK in text:
                text = text.replace(_MARK, entry, 1)
            else:
                text = text.replace("## 三、长期要点", "## 三、长期要点\n\n" + entry, 1)
        else:
            text += f"\n\n## 三、长期要点\n\n{entry}"
        grand_log.GRAND_LOG_FILE.write_text(text, encoding="utf-8")
        logger.info("每日复盘完成：%s", entry[:80])
        return entry
    except Exception as exc:  # noqa: BLE001
        logger.exception("每日复盘失败")
        return f"复盘失败：{exc}"


def ensure_scheduled() -> bool:
    """把复盘注册成 autopilot 的一条 custom 行为（幂等）。"""
    try:
        from . import autopilot  # noqa: PLC0415

        autopilot.init()
        for b in autopilot.list_behaviors():
            if b.get("kind") == "custom" and "复盘" in (b.get("text") or ""):
                return True
        autopilot.add_behavior(kind="custom", at=REVIEW_TIME, text="到点啦，今天该复盘了")
        logger.info("已注册每日复盘行为：%s", REVIEW_TIME)
        return True
    except Exception:  # noqa: BLE001
        logger.exception("注册每日复盘失败")
        return False
