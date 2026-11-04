import subprocess


def _set(text):
    p = subprocess.run(["clip"], input=text, text=True, encoding="utf-8", errors="replace")
    return p.returncode == 0


TOOL = {
    "name": "pc.clip.set",
    "title": "写电脑剪贴板",
    "desc": "把一段文字放进 Windows 剪贴板，之后可以 Ctrl+V 粘贴",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "要放进剪贴板的文字"}},
        "required": ["text"],
    },
    "run": lambda args, ctx: ({"ok": True, "output": "已经放进剪贴板了，可以粘贴"}
                              if _set(args.get("text", ""))
                              else {"ok": False, "output": "没写进去"}),
}
