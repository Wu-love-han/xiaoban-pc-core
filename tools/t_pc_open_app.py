"""pc.open_app：启动程序，或打开文件 / 网址。

和 pc.shell 的区别：这个只「打开」，不经过命令行解释器，所以不存在注入问题；
Windows 上走 os.startfile（等价于双击），Linux/macOS 走 xdg-open/open。
**不等待进程结束**，只确认已经交出去。
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import _common as C

# 常见的、可以直接按名字起的东西（不用给全路径）。给了就比直接 startfile 更可控。
_KNOWN_APPS: dict[str, str] = {
    "notepad": "notepad.exe",
    "记事本": "notepad.exe",
    "calc": "calc.exe",
    "计算器": "calc.exe",
    "mspaint": "mspaint.exe",
    "画图": "mspaint.exe",
    "explorer": "explorer.exe",
    "资源管理器": "explorer.exe",
    "cmd": "cmd.exe",
    "taskmgr": "taskmgr.exe",
    "任务管理器": "taskmgr.exe",
    "control": "control.exe",
    "控制面板": "control.exe",
}


def _is_url(s: str) -> bool:
    low = s.lower()
    return low.startswith(("http://", "https://", "file://", "mailto:"))


def _open_windows(target: str) -> None:
    os.startfile(target)  # type: ignore[attr-defined]


def _open_posix(target: str) -> None:
    opener = "open" if platform.system() == "Darwin" else "xdg-open"
    if not shutil.which(opener):
        raise FileNotFoundError(f"这台机器没有 {opener}")
    subprocess.Popen(
        [opener, target],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _open(target: str) -> None:
    if platform.system() == "Windows":
        _open_windows(target)
    else:
        _open_posix(target)


def run(args: dict, ctx: Any) -> dict:
    raw = str(args.get("target") or args.get("path") or args.get("app") or "").strip()
    if not raw:
        return C.fail("要打开什么呢？给我一个程序名、文件路径或者网址。", "MissingArg: target")

    # 1) 网址 / 协议链接：原样交给系统默认浏览器
    if _is_url(raw):
        _open(raw)
        return C.ok(f"用默认浏览器打开了 {raw}", target=raw, kind="url")

    # 2) 已知程序别名
    key = raw.lower()
    if key in _KNOWN_APPS:
        exe = _KNOWN_APPS[key]
        subprocess.Popen(
            [exe],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return C.ok(f"启动了{exe}", target=exe, kind="app")

    # 3) 当成路径：文件/目录存在就交给系统默认关联程序
    try:
        p = C.resolve_path(raw, ctx)
    except ValueError:
        return C.fail("没看懂要打开什么。", "MissingArg: target")

    if p.exists():
        _open(str(p))
        kind = "dir" if p.is_dir() else "file"
        return C.ok(f"打开了 {p}", target=str(p), kind=kind)

    # 4) 既不是已知别名也不是存在的路径：可能是 PATH 里的可执行文件
    exe = shutil.which(raw)
    if exe:
        subprocess.Popen(
            [exe],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return C.ok(f"启动了 {exe}", target=exe, kind="app")

    return C.fail(
        f"找不到「{raw}」：不是网址，本机也没这个文件，PATH 里也没这个程序。",
        "NotFound",
    )


TOOL = {
    "name": "pc.open_app",
    "title": "打开程序或文件",
    "desc": "启动一个程序（记事本、计算器、资源管理器等），或者用默认程序打开一个文件/文件夹/网址。只负责打开，不等待它关闭。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "要打开的东西：程序名（notepad）、绝对路径（E:\\WH\\a.txt）或网址（https://…）",
            }
        },
        "required": ["target"],
    },
    "run": C.guard(run),
}
