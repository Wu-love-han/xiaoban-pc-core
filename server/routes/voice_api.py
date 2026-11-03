"""`/api/voice`：语音模式（听 / 说 / 能力检查）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.toolbase import ToolContext, registry

from ..auth import require_auth

logger = logging.getLogger("pccore.api.voice")

router = APIRouter(prefix="/api/voice", tags=["voice"], dependencies=[Depends(require_auth)])


class SpeakIn(BaseModel):
    text: str
    rate: int = 0
    volume: int = 100


class ListenIn(BaseModel):
    seconds: float = 5.0


def _ctx() -> ToolContext:
    from pathlib import Path  # noqa: PLC0415

    return ToolContext(
        session_id="voice", call_id="voice",
        workspace=Path("."), config={},
    )


@router.get("/config")
async def voice_config():
    r = registry.execute("voice.mode", {"action": "config"}, _ctx())
    return {"ok": bool(r.get("ok")), "output": r.get("output"), "data": r.get("data")}


@router.post("/speak")
async def speak(body: SpeakIn):
    r = registry.execute("voice.mode", {
        "action": "speak", "text": body.text,
        "rate": body.rate, "volume": body.volume,
    }, _ctx())
    return {"ok": bool(r.get("ok")), "output": r.get("output")}


@router.post("/listen")
async def listen(body: ListenIn):
    r = registry.execute("voice.mode", {"action": "listen", "seconds": body.seconds}, _ctx())
    return {"ok": bool(r.get("ok")), "output": r.get("output"), "data": r.get("data")}
