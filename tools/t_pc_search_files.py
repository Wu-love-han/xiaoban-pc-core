"""pc.search_files：按文件名找，或者按内容找。

为什么要自己 walk 而不是 glob("**")：glob 没法限制深度、也没法干净地跳过
.venv/node_modules/.git，在 E:\\WH 这种目录上一跑就是几分钟。这里手写遍历，
深度上限 4、条目上限 30、命中即停，宁可少找一点也不卡住。

参数分两种用法：
- 只给 pattern（如 "*.py" 或 "todo*"）→ 按文件名匹配
- 再给 contains（如 "def run"）→ 在文件名命中/全部候选里再按内容过滤
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

from . import _common as C

MAX_RESULTS = 30
MAX_DEPTH = 4
SKIP_DIRS = {
    ".venv", "venv", "env", "__pycache__", "node_modules", ".git", ".idea",
    ".vscode", ".mypy_cache", ".pytest_cache", "dist", "build", ".tox",
    "$RECYCLE.BIN", "System Volume Information",
}
SKIP_EXT = {
    ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".zip", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".mp4", ".mp3", ".db",
    ".pdf", ".woff", ".woff2", ".ttf", ".bin", ".iso",
}
MAX_SCAN_BYTES = 512 * 1024  # 内容匹配时，单个文件最多读 512KB


def _name_match(name: str, pattern: str) -> bool:
    """pattern 没写通配符时按「包含」处理，模型更常写 "todo" 而不是 "*todo*"。"""
    pat = pattern.strip()
    if not pat:
        return False
    if any(ch in pat for ch in "*?["):
        return fnmatch.fnmatch(name.lower(), pat.lower())
    return pat.lower() in name.lower()


def _content_match(p: Path, needle: str) -> tuple[bool, int]:
    """在文本文件里找 needle，返回 (命中, 命中行号)。"""
    try:
        if p.stat().st_size > MAX_SCAN_BYTES:
            return False, 0
    except OSError:
        return False, 0
    try:
        raw = p.read_bytes()
    except OSError:
        return False, 0
    for enc in ("utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        return False, 0

    low = needle.lower()
    for i, line in enumerate(text.splitlines(), 1):
        if low in line.lower():
            return True, i
    return False, 0


def run(args: dict, ctx: Any) -> dict:
    root = C.resolve_path(args.get("path") or args.get("dir"), ctx, default_to_workspace=True)
    pattern = str(args.get("pattern") or args.get("name") or "").strip()
    contains = str(args.get("contains") or args.get("content") or "").strip()
    limit = int(args.get("limit") or MAX_RESULTS)
    limit = max(1, min(limit, MAX_RESULTS))

    if not pattern and not contains:
        return C.fail("要找什么呢？给我一个文件名（pattern）或者要搜的内容（contains）。", "MissingArg")
    if not root.exists():
        return C.fail(f"没有这个目录：{root}", "NotFound")
    if not root.is_dir():
        return C.fail(f"{root} 是个文件，不是目录。", "NotADirectory")

    # 用户明确要某个后缀时（*.db、*.png），别被「跳过二进制」的规则挡住
    wanted_ext = Path(pattern).suffix.lower() if pattern else ""

    hits: list[str] = []
    scanned = 0
    truncated = False

    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda e: None):
        cur = Path(dirpath)
        depth = len(cur.parts) - root_depth
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        else:
            dirnames[:] = [
                d for d in dirnames
                if d.lower() not in SKIP_DIRS and not d.startswith(".")
            ]

        for fn in filenames:
            if fn.lower() in SKIP_DIRS:
                continue
            ext = Path(fn).suffix.lower()
            # 二进制默认跳过，但用户点名要这个后缀就放行（*.db、*.png 这种是明确意图）
            if ext in SKIP_EXT and ext != wanted_ext:
                continue
            scanned += 1

            name_ok = _name_match(fn, pattern) if pattern else True
            if not name_ok:
                continue

            fp = cur / fn
            rel = str(fp.relative_to(root))
            if contains:
                hit, lineno = _content_match(fp, contains)
                if not hit:
                    continue
                hits.append(f"{rel}:{lineno}  ← 含「{contains}」")
            else:
                try:
                    size = C.human_size(fp.stat().st_size)
                except OSError:
                    size = "?"
                hits.append(f"{rel}  {size}")

            if len(hits) >= limit:
                truncated = True
                break
        if truncated:
            break

    if not hits:
        what = f"名字像「{pattern}」" if pattern else ""
        if contains:
            what += ("且" if what else "") + f"内容含「{contains}」"
        return C.ok(
            f"在 {root} 下没找到{what}的文件（翻了 {scanned} 个文件，最多看 {MAX_DEPTH} 层）。",
            root=str(root),
            hits=[],
            scanned=scanned,
        )

    head = f"在 {root} 下找到 {len(hits)}{'+' if truncated else ''} 个（翻了 {scanned} 个文件）"
    body = "\n".join(hits)
    if truncated:
        body += f"\n（只列前 {limit} 个，还有更多）"
    return C.ok(f"{head}\n{body}", root=str(root), hits=hits, scanned=scanned)


TOOL = {
    "name": "pc.search_files",
    "title": "找文件",
    "desc": "在一个目录下按文件名找文件（pattern 支持 * 通配，也可以只写关键词），或再用 contains 按文件内容搜。最多看 4 层深、返回 30 条。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "从哪个目录开始找；省略则从 workspace 开始",
            },
            "pattern": {
                "type": "string",
                "description": "文件名匹配：支持 *.py / todo* / 也可以直接写关键词",
            },
            "contains": {
                "type": "string",
                "description": "可选：文件内容里必须包含这个字符串",
            },
            "limit": {
                "type": "integer",
                "description": f"最多返回多少条（1-{MAX_RESULTS}，默认 {MAX_RESULTS}）",
            },
        },
        "required": [],
    },
    "run": C.guard(run),
}
