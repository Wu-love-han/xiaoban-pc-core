"""pc.list_dir：列目录。

给模型看的列表必须是「一眼能懂」的：先目录后文件，带大小和时间，
条目多就截断并说明还有多少——不然 400 字塞不下，模型会误以为只有这些。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from . import _common as C

MAX_ITEMS = 40


def _fmt_time(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "??-?? ??:??"


def run(args: dict, ctx: Any) -> dict:
    p = C.resolve_path(args.get("path"), ctx, default_to_workspace=True)

    if not p.exists():
        return C.fail(f"没有这个目录：{p}", "NotFound")
    if not p.is_dir():
        return C.fail(f"{p} 是个文件，不是目录。要读内容请用 pc.read_file。", "NotADirectory")

    try:
        entries = list(p.iterdir())
    except PermissionError:
        return C.fail(f"没有权限看 {p}。", "PermissionError")
    except OSError as exc:
        return C.fail(f"读不了 {p}：{exc.strerror or exc}", f"OSError: {exc}")

    dirs: list[Path] = []
    files: list[Path] = []
    for e in entries:
        try:
            (dirs if e.is_dir() else files).append(e)
        except OSError:
            files.append(e)

    # 名字排序，中文按 unicode 排，稳定可预期
    dirs.sort(key=lambda x: x.name.lower())
    files.sort(key=lambda x: x.name.lower())
    ordered = dirs + files

    if not ordered:
        return C.ok(f"{p} 是空的，什么都没有。", path=str(p), count=0, items=[])

    lines: list[str] = []
    shown = 0
    for e in ordered[:MAX_ITEMS]:
        try:
            st = e.stat()
            ts = _fmt_time(st.st_mtime)
            if e.is_dir():
                lines.append(f"[目录] {e.name}/  {ts}")
            else:
                lines.append(f"{e.name}  {C.human_size(st.st_size)}  {ts}")
            shown += 1
        except OSError:
            lines.append(f"{e.name}  （读不到属性）")
            shown += 1

    head = f"{p} 共 {len(ordered)} 项（{len(dirs)} 目录 / {len(files)} 文件）"
    body = "\n".join(lines)
    if len(ordered) > shown:
        body += f"\n…还有 {len(ordered) - shown} 项没列出来"

    return C.ok(
        f"{head}\n{body}",
        path=str(p),
        count=len(ordered),
        dirs=len(dirs),
        files=len(files),
        shown=shown,
    )


TOOL = {
    "name": "pc.list_dir",
    "title": "列目录",
    "desc": "看一个文件夹里有什么（子目录和文件，带大小和修改时间）。不给路径就列 workspace。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "目录的绝对路径；省略则列 workspace 目录",
            }
        },
    },
    "run": C.guard(run),
}
