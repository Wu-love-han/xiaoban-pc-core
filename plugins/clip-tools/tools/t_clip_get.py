import subprocess


def _get():
    ps = "Get-Clipboard -Raw"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout or ""


TOOL = {
    "name": "pc.clip.get",
    "title": "读电脑剪贴板",
    "desc": "读取 Windows 剪贴板里的文字内容",
    "danger": False,
    "params": {"type": "object", "properties": {}},
    "run": lambda args, ctx: {"ok": True, "output": _get() or "（剪贴板是空的）"},
}
