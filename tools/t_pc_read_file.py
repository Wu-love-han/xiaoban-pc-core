"""pc.read_file：读文本文件（≤200KB）。

编码按 utf-8 → gbk → latin-1 顺序试。latin-1 是兜底：它对任意字节都不抛异常，
所以最后一定能读出「东西」，只是可能是乱码——但乱码也好过整个工具失败。

注意：契约 6.1 规定 output ≤400 字（它要进模型上下文）。所以正文超过 400 字时
output 只放前面一段并说明总长，完整正文放在 data.text 里给程序用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _common as C

MAX_BYTES = 200 * 1024  # 契约 6.3：读文本文件（≤200KB）
_ENCODINGS = ("utf-8", "gbk", "latin-1")


def _decode(raw: bytes) -> tuple[str, str]:
    """返回 (正文, 实际用的编码)。utf-8 带 BOM 也能认。"""
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def run(args: dict, ctx: Any) -> dict:
    try:
        p = C.resolve_path(args.get("path"), ctx)
    except C.MissingPath:
        return C.fail("要读哪个文件呢？给我一个路径。", "MissingArg: path")

    if not p.exists():
        return C.fail(f"没有这个文件：{p}", "NotFound")
    if p.is_dir():
        return C.fail(f"{p} 是目录，不是文件。要看里面有什么请用 pc.list_dir。", "IsADirectory")

    try:
        size = p.stat().st_size
    except OSError as exc:
        return C.fail(f"读不到 {p} 的属性：{exc.strerror or exc}", f"OSError: {exc}")

    if size > MAX_BYTES:
        return C.fail(
            f"{p.name} 有 {C.human_size(size)}，超过 200KB 上限，我不整篇读。"
            f"可以让我读它的一部分，或者告诉我你具体想找什么。",
            "FileTooLarge",
        )
    if size == 0:
        return C.ok(f"{p.name} 是空文件，一个字都没有。", path=str(p), size=0, text="")

    try:
        raw = p.read_bytes()
    except PermissionError:
        return C.fail(f"没有权限读 {p}。", "PermissionError")
    except OSError as exc:
        return C.fail(f"读 {p} 失败：{exc.strerror or exc}", f"OSError: {exc}")

    text, enc = _decode(raw)
    lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)

    # output 只有 400 字预算：正文占大头，留一行头信息
    head = f"{p.name}（{C.human_size(size)}，{lines} 行，{enc}）"
    room = C.MAX_OUT - len(head) - 30
    if len(text) <= room:
        out = f"{head}\n{text}"
    else:
        out = f"{head}\n{text[:max(0, room)]}\n…（全文 {len(text)} 字，这里只放了开头）"

    return C.ok(
        out,
        path=str(p),
        size=size,
        lines=lines,
        encoding=enc,
        text=text,
        truncated=len(text) > room,
    )


TOOL = {
    "name": "pc.read_file",
    "title": "读文件",
    "desc": "读一个本机文本文件的内容（最大 200KB）。自动识别 UTF-8/GBK 编码。读代码、配置、笔记、日志时用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件的绝对路径；相对路径按 workspace 解析",
            }
        },
        "required": ["path"],
    },
    "run": C.guard(run),
}
