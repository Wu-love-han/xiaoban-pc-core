"""pc.write_file：写 / 覆盖文本文件（危险动作，需要人格先问一句）。

契约里 danger=True：会盖掉别人的东西，所以必须走审批。

两个刻意的设计：
1. 写之前先看原文件内容——如果原来有内容且和新内容不同，output 必须明说
   「覆盖了原有内容」，否则用户根本不知道自己丢了什么。
2. E: 盘是 exFAT，不支持原子改名（os.replace 会失败），所以直接 open(...,"w")
   写。中途断电可能留半截文件，这个代价换来的是「一定能写成功」。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _common as C


def _read_old(p: Path) -> str | None:
    """读原内容用于比较；读不了就当没有（不因为读失败而拒绝写）。"""
    try:
        raw = p.read_bytes()
    except OSError:
        return None
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def run(args: dict, ctx: Any) -> dict:
    try:
        # 相对路径落到 workspace，但必须给文件名——不然不知道该写进哪个文件
        p = C.resolve_path(args.get("path"), ctx)
    except C.MissingPath:
        return C.fail("要写到哪个文件呢？给我一个路径（比如 workspace/a.txt）。", "MissingArg: path")

    content = args.get("content")
    if content is None:
        content = args.get("text")
    if content is None:
        return C.fail("要写什么内容呢？content 是空的。", "MissingArg: content")
    text = str(content)

    if p.exists() and p.is_dir():
        return C.fail(f"{p} 是个目录，不能当文件写。", "IsADirectory")

    # 先建父目录：模型经常写 workspace/a/b/c.txt 这种还不存在的路径
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return C.fail(
            f"建不了目录 {p.parent}：{exc.strerror or exc}", f"OSError: {exc}"
        )

    existed = p.exists()
    old = _read_old(p) if existed else None
    overwritten = existed and old is not None and old != text
    unchanged = existed and old == text

    try:
        # exFAT：直接写，不做原子改名
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    except PermissionError:
        return C.fail(f"没有权限写 {p}（文件可能被别的程序占着）。", "PermissionError")
    except OSError as exc:
        return C.fail(f"写 {p} 失败：{exc.strerror or exc}", f"OSError: {exc}")

    n_lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)

    if unchanged:
        out = f"{p} 里本来就是这段内容，我按原样又写了一遍（没变化）。"
    elif overwritten:
        out = (
            f"写好了 {p}（{len(text)} 字，{n_lines} 行）。"
            f"注意：覆盖了原有内容，原来那 {len(old or '')} 字没了。"
        )
    elif existed:
        out = f"写好了 {p}（{len(text)} 字，{n_lines} 行），原来那个空文件被填上了。"
    else:
        out = f"新建并写好了 {p}（{len(text)} 字，{n_lines} 行）。"

    return C.ok(
        out,
        path=str(p),
        bytes=len(text.encode("utf-8")),
        chars=len(text),
        lines=n_lines,
        created=not existed,
        overwritten=overwritten,
    )


TOOL = {
    "name": "pc.write_file",
    "title": "写文件",
    "desc": "把一段文本写进文件，父目录不存在会自动建。文件已存在就整个覆盖（原有内容会丢）。只能写文本。",
    "danger": True,
    "params": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件绝对路径；相对路径按 workspace 解析",
            },
            "content": {
                "type": "string",
                "description": "要写入的完整文本内容",
            },
        },
        "required": ["path", "content"],
    },
    "run": C.guard(run),
}
