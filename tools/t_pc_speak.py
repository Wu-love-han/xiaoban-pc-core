"""pc.speak：让电脑开口说话（Windows SAPI 语音合成）。

小伴的需求：「尝试搭建语音模式」
- 支持中文（Microsoft Huihui）
- 可选语速/音量
- 默认异步，不阻塞对话
"""

from __future__ import annotations

import re
import subprocess
import threading
from typing import Any

from . import _common as C

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _xml_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def speak(text: str, rate: int = 0, volume: int = 100, voice: str = "") -> tuple[bool, str]:
    """同步说话，返回 (是否成功, 说明)。"""
    text = (text or "").strip()
    if not text:
        return False, "没有要说的内容"

    # 语速 -10..10，音量 0..100
    rate = max(-10, min(10, int(rate)))
    volume = max(0, min(100, int(volume)))

    voice_line = ""
    if voice:
        voice_line = f"$s.SelectVoice('{voice.replace(chr(39), '')}');"

    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Rate = {rate};$s.Volume = {volume};"
        f"{voice_line}"
        f"$s.Speak([System.Net.WebUtility]::HtmlDecode('{_xml_escape(text)[:800].replace(chr(39), chr(8217))}'));"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=90, creationflags=_CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            err = (r.stderr or b"").decode("gbk", "replace")[:200]
            return False, err or "语音合成失败"
        return True, f"说完了（{len(text)} 字）"
    except subprocess.TimeoutExpired:
        return False, "说话超时（可能卡住了）"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def run(args: dict, ctx: Any) -> dict:
    text = str(args.get("text") or "")
    if not text.strip():
        return C.fail("要我说什么？", "MissingArg: text")
    if len(text) > 800:
        return C.fail("一次最多说 800 字。", "TooLong")

    rate = args.get("rate", 0)
    volume = args.get("volume", 100)
    voice = str(args.get("voice") or "")

    if bool(args.get("async")):
        t = threading.Thread(target=speak, args=(text, rate, volume, voice), daemon=True)
        t.start()
        return C.ok(f"开始说了（{len(text)} 字）", async_=True, text=text)

    ok, msg = speak(text, rate, volume, voice)
    if not ok:
        return C.fail(f"说话失败：{msg}", "SpeakFailed")
    return C.ok(msg, text=text, rate=rate, volume=volume)


TOOL = {
    "name": "pc.speak",
    "title": "说话（语音合成）",
    "desc": "用电脑的喇叭把文字念出来（中文用 Huihui 语音）。想用语音回应、念提醒、播报内容时用。rate 是语速 -10~10，volume 是音量 0~100。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要说的话"},
            "rate": {"type": "integer", "description": "语速 -10（慢）到 10（快），默认 0"},
            "volume": {"type": "integer", "description": "音量 0-100，默认 100"},
            "async": {"type": "boolean", "description": "true = 不等着说完就返回"},
        },
        "required": ["text"],
    },
    "run": C.guard(run),
}
