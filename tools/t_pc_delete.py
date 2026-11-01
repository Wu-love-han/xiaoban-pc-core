"""pc.delete：删除文件或空目录（危险动作，需要人格先问一句）。

**刻意不做递归删除。** 这个工具一旦能 rm -rf，一次误判就是不可恢复的损失；
契约 6.3 也只写了「删除文件/空目录」。所以非空目录一律拒绝，并告诉用户
里面还有什么——让他自己决定是不是先清空，或者换个说法。

另外挡住几个明显不该删的：盘符根目录、用户主目录本身。这不算过度保护，
纯粹是「模型把 E:\\ 当成 workspace 传进来」这种事故太容易发生。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _common as C


def _protected(p: Path) -> str:
    """返回拒绝理由；空串表示可以删。"""
    try:
        rp = p.resolve()
    except OSError:
        rp = p

    if rp.parent == rp:
        return "这是盘符根目录，删不得"
    try:
        if rp == Path.home().resolve():
            return "这是你的用户主目录，删不得"
    except OSError:
        pass
    # Windows 系统目录
    win = rp.drive.upper()
    if win and str(rp).rstrip("\\/").upper() in (
        f"{win}\\WINDOWS",
        f"{win}\\WINDOWS\\SYSTEM32",
        f"{win}\\PROGRAM FILES",
        f"{win}\\PROGRAM FILES (X86)",
        f"{win}\\USERS",
    ):
        return "这是系统目录，删不得"
    return ""


def run(args: dict, ctx: Any) -> dict:
    try:
        p = C.resolve_path(args.get("path"), ctx)
    except C.MissingPath:
        return C.fail("要删哪个文件呢？给我一个路径。", "MissingArg: path")

    if not p.exists() and not p.is_symlink():
        return C.fail(f"{p} 本来就不存在，没什么可删的。", "NotFound")

    why = _protected(p)
    if why:
        return C.fail(f"{p} 我不删：{why}。", "Refused")

    is_link = p.is_symlink()
    is_dir = p.is_dir() and not is_link

    # 非空目录拒绝：这是本工具最重要的边界
    if is_dir:
        try:
            children = list(p.iterdir())
        except PermissionError:
            return C.fail(f"没有权限看 {p} 里有什么，为了安全我不删。", "PermissionError")
        except OSError as exc:
            return C.fail(f"看不了 {p}：{exc.strerror or exc}", f"OSError: {exc}")

        if children:
            names = "、".join(c.name for c in children[:5])
            more = f" 等 {len(children)} 项" if len(children) > 5 else ""
            return C.fail(
                f"{p} 不是空目录（里面还有 {names}{more}），我不递归删。"
                f"要清空的话，得先一样一样处理里面的东西。",
                "DirectoryNotEmpty",
            )

    try:
        if is_dir:
            p.rmdir()  # 只对空目录成功
            kind = "空目录"
        else:
            p.unlink()
            kind = "链接" if is_link else "文件"
    except PermissionError:
        return C.fail(f"没有权限删 {p}（可能被别的程序占着）。", "PermissionError")
    except OSError as exc:
        return C.fail(f"删 {p} 失败：{exc.strerror or exc}", f"OSError: {exc}")

    return C.ok(f"删掉了{kind} {p}。", path=str(p), kind=kind)


TOOL = {
    "name": "pc.delete",
    "title": "删除文件",
    "desc": "删掉一个文件或一个空文件夹。非空文件夹会被拒绝（不递归删）。删了就找不回来。",
    "danger": True,
    "params": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要删除的文件或空目录的绝对路径；相对路径按 workspace 解析",
            }
        },
        "required": ["path"],
    },
    "run": C.guard(run),
}
