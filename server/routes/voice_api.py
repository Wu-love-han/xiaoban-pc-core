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
    voice: str = ""


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
    voices = []
    try:
        from tools import t_pc_speak  # noqa: PLC0415

        voices = t_pc_speak.list_voices()
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": bool(r.get("ok")),
        "output": r.get("output"),
        "data": r.get("data"),
        "voices": voices,
    }


@router.get("/voices")
async def voice_list():
    try:
        from tools import t_pc_speak  # noqa: PLC0415

        return {"ok": True, "voices": t_pc_speak.list_voices()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "voices": [], "error": str(exc)}


@router.post("/speak")
async def speak(body: SpeakIn):
    r = registry.execute("pc.speak", {
        "text": body.text, "rate": body.rate,
        "volume": body.volume, "voice": body.voice,
    }, _ctx())
    return {"ok": bool(r.get("ok")), "output": r.get("output")}


@router.post("/listen")
async def listen(body: ListenIn):
    r = registry.execute("voice.mode", {"action": "listen", "seconds": body.seconds}, _ctx())
    return {"ok": bool(r.get("ok")), "output": r.get("output"), "data": r.get("data")}


@router.post("/stop")
async def voice_stop():
    try:
        from tools import t_pc_speak  # noqa: PLC0415

        return {"ok": True, "stopped": t_pc_speak.stop()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
