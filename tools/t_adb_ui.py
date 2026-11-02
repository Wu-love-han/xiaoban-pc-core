"""手机界面结构树（快，不用截图）。"""

from __future__ import annotations

from tools import _adb_common as A


def _run(args, ctx):
    force = bool(args.get("refresh"))
    ok, data = A.ui_tree(force=force)
    if not ok:
        return {"ok": False, "output": str(data)}
    if not data:
        return {"ok": True, "output": "当前界面没有可读元素（可能是空屏/App 屏蔽）"}
    lines = []
    for i, e in enumerate(data[:40]):
        label = e["text"] or e["desc"] or e["id"] or e["class"]
        tag = "可点" if e["clickable"] else "  "
        lines.append(f"{i}. [{tag}] {label} @{e['center']}")
    return {
        "ok": True,
        "output": f"界面元素 {len(data)} 个（显示前 40）：\n" + "\n".join(lines),
        "data": {"count": len(data), "elements": data[:40]},
    }


TOOL = {
    "name": "phone.ui_tree",
    "title": "手机界面结构树",
    "desc": "读当前界面的文字+坐标+可点击状态（比截图快，推荐用这个）",
    "danger": False,
    "params": {"type": "object", "properties": {"refresh": {"type": "boolean", "description": "true=跳过缓存强制重读"}}},
    "run": _run,
}
