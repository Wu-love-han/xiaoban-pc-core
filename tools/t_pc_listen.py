"""pc.listen：听用户说话（Windows 语音识别，中文）。

小伴的需求：「尝试搭建语音模式」
- 用默认麦克风录音
- 用系统中文识别器转文字
- 结果写文件读回来，避开控制台编码坑
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import _common as C

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_PS = r'''
Add-Type -AssemblyName System.Speech
$out = "__OUT__"
try {
  $id = ([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers())[0].Id
  $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine($id)
  $rec.SetInputToDefaultAudioDevice()
  $rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
  $r = $rec.Recognize([TimeSpan]::FromSeconds(__SECS__))
  if ($r) {
    [System.IO.File]::WriteAllText($out, $r.Text, [System.Text.Encoding]::UTF8)
  } else {
    [System.IO.File]::WriteAllText($out, "", [System.Text.Encoding]::UTF8)
  }
} catch {
  [System.IO.File]::WriteAllText($out, "ERR:" + $_.Exception.Message, [System.Text.Encoding]::UTF8)
}
'''


def run(args: dict, ctx: Any) -> dict:
    try:
        secs = float(args.get("seconds") or 5)
    except (TypeError, ValueError):
        secs = 5.0
    secs = max(1.0, min(30.0, secs))

    out = Path(tempfile.gettempdir()) / f"xiaoban_listen_{int(time.time())}.txt"
    script = _PS.replace("__OUT__", str(out)).replace("__SECS__", str(int(secs)))

    t0 = time.time()
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=int(secs) + 30, creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return C.fail("听的时间超了，可能麦克风卡住。", "Timeout")
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"录音失败：{exc}", f"{type(exc).__name__}")

    elapsed = time.time() - t0
    text = ""
    try:
        text = out.read_text(encoding="utf-8-sig", errors="replace").strip().lstrip("\ufeff")
        out.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass

    if text.startswith("ERR:"):
        return C.fail(
            f"语音识别没起来：{text[4:][:200]}。可能是麦克风没接，或者系统没装中文语音识别。",
            "RecognizerError",
        )

    if not text:
        return C.ok(
            f"听了 {elapsed:.0f} 秒，没听清你说什么（可能太小声或者没说话）。",
            heard="", seconds=round(elapsed, 1),
        )

    return C.ok(f"我听到你说：「{text}」", heard=text, seconds=round(elapsed, 1))


TOOL = {
    "name": "pc.listen",
    "title": "听用户说话",
    "desc": "打开麦克风听几秒，把用户说的话转成文字。想用语音交互时用。默认听 5 秒。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "seconds": {"type": "number", "description": "听多久（1-30 秒），默认 5"},
        },
    },
    "run": C.guard(run),
}
