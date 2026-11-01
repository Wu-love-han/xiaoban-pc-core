"""pc.append_file：往文件末尾追加文本（不覆盖）。

和 pc.write_file 的区别：这个不会丢东西，所以不是危险动作，不需要审批。

一个小决定：文件已有内容、但结尾没有换行时，默认先补一个换行再追加
（参数 ensure_newline=false 可以关掉）。理由：追加最常用的场景是加一行日志/一条待办，
不补换行会和新内容粘成一行，几乎总是错的。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _common as C


def _tail(p: Path) -> str:
    """读文件最后 1 个字节，判断结尾是不是换行。"""
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size <= 0:
                return ""
            f.seek(size - 1)
            b = f.read(1)
        return b.decode("latin-1")
    except OSError:
        return ""


def run(args: dict, ctx: Any) -> dict:
    try:
        p = C.resolve_path(args.get("path"), ctx)
    except C.MissingPath:
        return C.fail("要追加到哪个文件呢？给我一个路径。", "MissingArg: path")

    content = args.get("content")
    if content is None:
        content = args.get("text")
    if content is None:
        return C.fail("要追加什么内容呢？content 是空的。", "MissingArg: content")
    text = str(content)

    if p.exists() and p.is_dir():
        return C.fail(f"{p} 是个目录，不能当文件写。", "IsADirectory")

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return C.fail(f"建不了目录 {p.parent}：{exc.strerror or exc}", f"OSError: {exc}")

    existed = p.exists()
    old_size = p.stat().st_size if existed else 0
    ensure_nl = args.get("ensure_newline", True)
    added_nl = False

    payload = text
    if bool(ensure_nl) and old_size > 0 and _tail(p) not in ("\n", "\r"):
        payload = "\n" + text
        added_nl = True

    try:
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write(payload)
    except PermissionError:
        return C.fail(f"没有权限写 {p}（文件可能被占着）。", "PermissionError")
    except OSError as exc:
        return C.fail(f"追加到 {p} 失败：{exc.strerror or exc}", f"OSError: {exc}")

    new_size = p.stat().st_size
    verb = "追加到" if existed else "新建并写入"
    extra = "（原文件结尾没换行，我先补了一个换行）" if added_nl else ""
    return C.ok(
        f"{verb} {p}：加了 {len(text)} 字{extra}，文件从 {C.human_size(old_size)} 变成 "
        f"{C.human_size(new_size)}。",
        path=str(p),
        added_chars=len(text),
        size=new_size,
        created=not existed,
    )


TOOL = {
    "name": "pc.append_file",
    "title": "追加内容",
    "desc": "往一个文件末尾追加文本，原有内容保留。文件不存在就新建。适合记日志、加待办、往清单里加一条。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件绝对路径；相对路径按 workspace 解析",
            },
            "content": {"type": "string", "description": "要追加的文本"},
            "ensure_newline": {
                "type": "boolean",
                "description": "原文件结尾没有换行时，先补一个换行再追加（默认 true）",
            },
        },
        "required": ["path", "content"],
    },
    "run": C.guard(run),
}
