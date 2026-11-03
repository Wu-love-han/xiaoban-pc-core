"""voice.mode：一键语音对话（听 → 想 → 说）。

小伴的需求：「尝试搭建语音模式」

这个工具只负责「听 + 说」两端，中间怎么想交给模型：
- action=listen  听一句话，返回文字
- action=speak   说一句话
- action=config  看语音配置（有没有中文语音/识别器）
"""

from __future__ import annotations

import subprocess
from typing import Any

from . import _common as C
from . import t_pc_listen as L
from . import t_pc_speak as S

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _probe() -> dict:
    """看这台机器有没有中文语音和中文识别器。"""
    out = {"tts": [], "stt": []}
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Add-Type -AssemblyName System.Speech;"
             "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | "
             "ForEach-Object { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture };"
             "Write-Output '---';"
             "[System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | "
             "ForEach-Object { $_.Name + '|' + $_.Culture }"],
            capture_output=True, timeout=25, creationflags=_CREATE_NO_WINDOW,
        )
        text = (r.stdout or b"").decode("utf-8", "replace")
        part = 0
        for line in text.splitlines():
            line = line.strip()
            if line == "---":
                part = 1
                continue
            if not line:
                continue
            out["tts" if part == 0 else "stt"].append(line)
    except Exception:  # noqa: BLE001
        pass
    return out


def run(args: dict, ctx: Any) -> dict:
    action = str(args.get("action") or "listen").strip().lower()

    if action == "config":
        info = _probe()
        zh_tts = [v for v in info["tts"] if "zh" in v.lower()]
        zh_stt = [v for v in info["stt"] if "zh" in v.lower()]
        return C.ok(
            f"语音合成：{len(info['tts'])} 个（中文 {len(zh_tts)} 个）\n"
            f"语音识别：{len(info['stt'])} 个（中文 {len(zh_stt)} 个）\n"
            + ("中文语音和识别都齐了，可以语音对话。"
               if zh_tts and zh_stt else "缺中文语音或识别器，可能需要装语言包。"),
            tts=info["tts"], stt=info["stt"], zh_ok=bool(zh_tts and zh_stt),
        )

    if action == "speak":
        text = str(args.get("text") or "")
        if not text.strip():
            return C.fail("要说什么？", "MissingArg: text")
        ok, msg = S.speak(text, args.get("rate", 0), args.get("volume", 100))
        return C.ok(msg, said=text) if ok else C.fail(msg, "SpeakFailed")

    # listen
    return L.run({"seconds": args.get("seconds", 5)}, ctx)


TOOL = {
    "name": "voice.mode",
    "title": "语音模式",
    "desc": "语音对话的两端：action=listen 听用户说一句话转成文字；action=speak 把文字念出来；action=config 检查中文语音支持。想做语音交互时用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["listen", "speak", "config"]},
            "text": {"type": "string", "description": "speak 时要说的内容"},
            "seconds": {"type": "number", "description": "listen 时听多久，默认 5"},
        },
    },
    "run": C.guard(run),
}
