"""pc.mkdir：建目录。

和写文件一样支持多级（parents=True）。已经存在算成功——幂等比报错有用，
模型经常重试同一个动作。
"""

from __future__ import annotations

from typing import Any

from . import _common as C


def run(args: dict, ctx: Any) -> dict:
    try:
        p = C.resolve_path(args.get("path"), ctx)
    except C.MissingPath:
        return C.fail("要建哪个目录呢？给我一个路径。", "MissingArg: path")

    if p.exists():
        if p.is_dir():
            return C.ok(f"{p} 这个目录本来就有，不用再建。", path=str(p), created=False)
        return C.fail(f"{p} 已经是个文件了，没法当目录建。", "FileExists")

    try:
        p.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        return C.ok(f"{p} 这个目录本来就有。", path=str(p), created=False)
    except PermissionError:
        return C.fail(f"没有权限在 {p.parent} 下建目录。", "PermissionError")
    except OSError as exc:
        return C.fail(f"建目录失败：{exc.strerror or exc}", f"OSError: {exc}")

    return C.ok(f"建好了目录 {p}。", path=str(p), created=True)


TOOL = {
    "name": "pc.mkdir",
    "title": "建目录",
    "desc": "新建一个文件夹，多级路径会自动补齐（a/b/c 一次建完）。已经存在就直接说存在。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要建的目录路径；相对路径按 workspace 解析",
            }
        },
        "required": ["path"],
    },
    "run": C.guard(run),
}
