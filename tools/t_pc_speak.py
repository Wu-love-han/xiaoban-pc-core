"""pc.speak：让电脑开口说话（Windows SAPI COM 接口）。

为什么用 COM 不用 System.Speech：
  这台机器上 System.Speech 的 SelectVoice 会静默失败（语音名返回空），
  Speak() 什么也不做。COM 的 SAPI.SpVoice 正常。实测踩过。

支持中文语音（Microsoft Huihui）。
"""

from __future__ import annotations

import subprocess
import threading
from typing import Any

from . import _common as C

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_running: dict = {"proc": None}
_running_lock = threading.RLock()


def _ps_quote(s: str) -> str:
    """PowerShell 单引号字符串转义。"""
    return (s or "").replace("'", "''")


def speak(text: str, rate: int = 0, volume: int = 100, voice: str = "", wait: bool = True) -> tuple[bool, str]:
    """说话。rate -10..10，volume 0..100。"""
    text = (text or "").strip()
    if not text:
        return False, "没有要说的内容"

    rate = max(-10, min(10, int(rate)))
    volume = max(0, min(100, int(volume)))

    # 选语音：优先中文
    pick = ""
    if voice:
        pick = f"if ($d -match '{_ps_quote(voice)}') {{ $sel = $toks.Item($i); break }}"
    else:
        pick = "if ($d -match 'Chinese|Huihui|zh-CN|Yaoyao|Kangkang') { $sel = $toks.Item($i); break }"

    script = (
        "$ErrorActionPreference='Stop';"
        "try {"
        "$v = New-Object -ComObject SAPI.SpVoice;"
        "$toks = $v.GetVoices();"
        "$sel = $null;"
        "for ($i=0; $i -lt $toks.Count; $i++) {"
        "  $d = $toks.Item($i).GetDescription();"
        f"  {pick}"
        "}"
        "if ($sel -eq $null -and $toks.Count -gt 0) { $sel = $toks.Item(0) }"
        "if ($sel -ne $null) { $v.Voice = $sel };"
        f"$v.Volume = {volume};"
        f"$v.Rate = {rate};"
        f"$v.Speak('{_ps_quote(text[:800])}', {0 if wait else 1}) | Out-Null;"
        "Write-Output 'OK';"
        "} catch { Write-Output ('ERR:' + $_.Exception.Message) }"
    )

    try:
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_CREATE_NO_WINDOW,
        )
        with _running_lock:
            _running["proc"] = proc
        try:
            stdout_b, stderr_b = proc.communicate(timeout=120)
        finally:
            with _running_lock:
                _running["proc"] = None
        class _R:
            returncode = proc.returncode
            stdout = stdout_b
            stderr = stderr_b
        r = _R()
        out = (r.stdout or b"").decode("utf-8", "replace").strip()
        err = (r.stderr or b"").decode("gbk", "replace").strip()
        if "ERR:" in out:
            return False, out.split("ERR:", 1)[1].strip()[:200]
        if "OK" not in out:
            return False, (err or out or "语音合成没有返回结果")[:200]
        return True, f"说了 {len(text)} 个字" + ("" if wait else "（不等说完就返回）")
    except subprocess.TimeoutExpired:
        return False, "说话超时"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def list_voices() -> list[dict]:
    """列出系统里的语音。"""
    script = (
        "try {"
        "$v = New-Object -ComObject SAPI.SpVoice;"
        "$toks = $v.GetVoices();"
        "for ($i=0; $i -lt $toks.Count; $i++) {"
        "  Write-Output ($i.ToString() + '|' + $toks.Item($i).GetDescription())"
        "}"
        "} catch { Write-Output ('ERR:' + $_.Exception.Message) }"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=30, creationflags=_CREATE_NO_WINDOW,
        )
        out = (r.stdout or b"").decode("utf-8", "replace")
        voices = []
        for line in out.splitlines():
            line = line.strip()
            if "|" in line and not line.startswith("ERR"):
                idx, desc = line.split("|", 1)
                voices.append({"index": idx, "name": desc, "chinese": bool(
                    any(k in desc for k in ("Chinese", "Huihui", "Yaoyao", "Kangkang"))) })
        return voices
    except Exception:  # noqa: BLE001
        return []


def run(args: dict, ctx: Any) -> dict:
    action = str(args.get("action") or "speak").strip().lower()

    if action == "voices":
        vs = list_voices()
        if not vs:
            return C.fail("读不到系统语音", "NoVoices")
        lines = [f"- [{v['index']}] {v['name']}" + ("（中文）" if v["chinese"] else "") for v in vs]
        return C.ok(f"系统有 {len(vs)} 个语音：\n" + "\n".join(lines), voices=vs)

    text = str(args.get("text") or "")
    if not text.strip():
        return C.fail("要我说什么？", "MissingArg: text")
    if len(text) > 800:
        return C.fail("一次最多说 800 字。", "TooLong")

    rate = args.get("rate", 0)
    volume = args.get("volume", 100)
    voice = str(args.get("voice") or "")
    async_ = bool(args.get("async"))

    if async_:
        t = threading.Thread(target=speak, args=(text, rate, volume, voice, False), daemon=True)
        t.start()
        return C.ok(f"开始说了（{len(text)} 字）", text=text, async_=True)

    ok, msg = speak(text, rate, volume, voice, wait=True)
    if not ok:
        return C.fail(f"说话失败：{msg}", "SpeakFailed")
    return C.ok(msg, text=text, rate=rate, volume=volume)


TOOL = {
    "name": "pc.speak",
    "title": "说话（语音合成）",
    "desc": "用电脑喇叭念文字。走 SAPI COM 接口，中文用 Huihui。action=voices 可以列系统语音。rate 语速 -10~10，volume 音量 0~100。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["speak", "voices"], "description": "speak=说话（默认），voices=列语音"},
            "text": {"type": "string", "description": "要说的话"},
            "rate": {"type": "integer", "description": "语速 -10 到 10，默认 0"},
            "volume": {"type": "integer", "description": "音量 0-100，默认 100"},
            "voice": {"type": "string", "description": "指定语音名（可省略，默认选中文）"},
            "async": {"type": "boolean", "description": "true = 不等说完就返回"},
        },
    },
    "run": C.guard(run),
}


def stop() -> bool:
    """打断正在说的话。"""
    with _running_lock:
        proc = _running.get("proc")
    if proc is None:
        return False
    try:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            proc.kill()
        return True
    except Exception:  # noqa: BLE001
        return False
