"""`/api/grandlog`：总志读写（用户笔记："开始前读总志"）。

只读为主 + 一个手动追加接口，方便前端展示/调试。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import grand_log

from ..auth import require_auth

logger = logging.getLogger("pccore.api.grandlog")

router = APIRouter(prefix="/api/grandlog", tags=["grandlog"], dependencies=[Depends(require_auth)])


class AppendIn(BaseModel):
    text: str


@router.get("")
async def get_grandlog():
    try:
        grand_log.ensure_file()
        return {
            "ok": True,
            "path": str(grand_log.GRAND_LOG_FILE),
            "content": grand_log.read(),
            "snippet": grand_log.state_snippet(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("读总志失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/review")
async def daily_review():
    """每日复盘摘要。"""
    try:
        return {"ok": True, "summary": grand_log.daily_compact()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/append")
async def append_to_grandlog(body: AppendIn):
    """手动往总志里追加一条（写进"长期要点"区，不删任何内容）。"""
    try:
        grand_log.ensure_file()
        text = grand_log.read()
        entry = f"- `{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}` {body.text.strip()}"
        if "## 三、长期要点" in text:
            text = text.replace("## 三、长期要点\n\n- （暂无）", "## 三、长期要点\n\n" + entry, 1)
            if entry not in text:
                text = text.replace("## 三、长期要点", "## 三、长期要点\n\n" + entry, 1)
        else:
            text += "\n\n## 三、长期要点\n\n" + entry

        grand_log.GRAND_LOG_FILE.write_text(text, encoding="utf-8")
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        logger.exception("追加总志失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
