"""pc.self_update：读/改自己的代码和配置（带备份 + 语法校验 + 出错自动回滚）。

小伴的需求：「能读取并修改我自己这一端的代码/配置，用户提优化需求时直接落地」

安全设计（这是唯一能改自己源码的口子，所以写死几条）：
1. 只能动 E:\\WH\\pc-core 下面，且不能碰 data/ .git/ .venv/ logs/ workspace/
2. 每次写都先存备份：<文件>.bak-<时间戳>，出问题能回滚
3. Python 文件写完立刻 py_compile 校验，不通过就自动还原
4. 红线文件（reviewer.py / auth.py）必须显式 confirm=true 才允许改
5. 改完告诉模型「要不要重启才生效」，不擅自重启
"""

from __future__ import annotations

import py_compile
import shutil
import time
from pathlib import Path
from typing import Any

from . import _common as C

ROOT = Path(r"E:\WH\pc-core")

# 不许碰的目录
_FORBIDDEN_DIRS = {
    "data", ".git", ".venv", "logs", "workspace", "__pycache__", "node_modules", "plugins",
}
# 改了要额外确认的文件（涉及安全底线）
_CONFIRM_FILES = {
    "core/reviewer.py",     # 审核红线
    "server/auth.py",       # 鉴权
    "tools/t_pc_self_update.py",  # 自己（防止自己把自己改坏）
}
# 允许改的扩展名
_ALLOWED_EXT = {".py", ".md", ".json", ".yml", ".yaml", ".txt", ".html", ".js", ".css", ".sh", ".bat"}

MAX_READ = 200_000


def _resolve(rel: str) -> Path:
    rel = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise ValueError("要给我一个相对路径，比如 core/brain.py")
    p = (ROOT / rel).resolve()
    try:
        p.relative_to(ROOT.resolve())
    except ValueError:
        raise ValueError("路径跑出项目目录了，不允许") from None
    # 目录黑名单
    parts = set(p.relative_to(ROOT).parts)
    if parts & _FORBIDDEN_DIRS:
        raise ValueError(f"这个目录不允许改：{', '.join(sorted(parts & _FORBIDDEN_DIRS))}")
    return p


def _backup(p: Path) -> str:
    if not p.exists():
        return ""
    bak = p.with_suffix(p.suffix + f".bak-{int(time.time())}")
    try:
        shutil.copy2(p, bak)
        return str(bak)
    except Exception:  # noqa: BLE001
        return ""


def _list_files() -> list[str]:
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if set(rel.parts) & _FORBIDDEN_DIRS:
            continue
        if p.suffix.lower() not in _ALLOWED_EXT:
            continue
        if ".bak-" in p.name:
            continue
        out.append(str(rel).replace("\\", "/"))
    return sorted(out)


def run(args: dict, ctx: Any) -> dict:
    action = str(args.get("action") or "").strip().lower()

    # ---- 列文件 ----
    if action == "list":
        files = _list_files()
        head = files[:120]
        return C.ok(
            f"项目里有 {len(files)} 个可编辑文件，先列 {len(head)} 个：\n" + "\n".join(head),
            files=head, total=len(files),
        )

    # ---- 读 ----
    if action == "read":
        try:
            p = _resolve(str(args.get("path") or ""))
        except ValueError as exc:
            return C.fail(str(exc), "BadPath")
        if not p.exists():
            return C.fail(f"没有这个文件：{p.relative_to(ROOT)}", "NotFound")
        if p.stat().st_size > MAX_READ:
            return C.fail(f"文件太大（{p.stat().st_size} 字节），用 pc.read_file 分段读", "TooLarge")
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return C.fail(f"读失败：{exc}", "ReadFailed")
        return C.ok(text[:30000], path=str(p.relative_to(ROOT)), size=len(text))

    # ---- 写 ----
    if action == "write":
        rel = str(args.get("path") or "")
        content = args.get("content")
        if content is None:
            return C.fail("要给我 content（完整新内容）", "MissingArg: content")
        content = str(content)
        try:
            p = _resolve(rel)
        except ValueError as exc:
            return C.fail(str(exc), "BadPath")

        rel_norm = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel_norm in _CONFIRM_FILES and not bool(args.get("confirm")):
            return C.fail(
                f"{rel_norm} 是安全底线文件，改它必须显式 confirm=true。"
                "先跟用户确认要改什么、为什么改。",
                "NeedConfirm",
            )

        old_text = ""
        if p.exists():
            try:
                old_text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

        bak = _backup(p)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return C.fail(f"写失败：{exc}", "WriteFailed")

        # Python 语法校验，不通过立刻回滚
        if p.suffix.lower() == ".py":
            try:
                py_compile.compile(str(p), doraise=True, cfile=str(p) + ".pyc-check")
                Path(str(p) + ".pyc-check").unlink(missing_ok=True)
            except py_compile.PyCompileError as exc:
                if bak:
                    shutil.copy2(bak, p)
                else:
                    p.unlink(missing_ok=True)
                return C.fail(
                    f"语法错误，已自动回滚到修改前：{str(exc)[:300]}",
                    "SyntaxError",
                )

        # JSON 校验
        if p.suffix.lower() == ".json":
            import json as _json

            try:
                _json.loads(content)
            except Exception as exc:  # noqa: BLE001
                if bak:
                    shutil.copy2(bak, p)
                return C.fail(f"JSON 格式不对，已回滚：{exc}", "BadJson")

        restart = p.suffix.lower() in (".py",) or rel_norm.startswith(("server/", "core/"))
        return C.ok(
            f"改好了：{rel_norm}（{len(old_text)} → {len(content)} 字节）"
            + (f"，备份在 {Path(bak).name}" if bak else "")
            + ("。这是 Python/服务端文件，要重启后端才生效。" if restart else "。"),
            path=rel_norm, backup=bak, needs_restart=restart,
            size_before=len(old_text), size_after=len(content),
        )

    # ---- 查找替换（比整篇覆盖安全）----
    if action == "patch":
        try:
            p = _resolve(str(args.get("path") or ""))
        except ValueError as exc:
            return C.fail(str(exc), "BadPath")
        find = str(args.get("find") or "")
        repl = str(args.get("replace") or "")
        if not find:
            return C.fail("要给我 find（原文片段）", "MissingArg: find")
        if not p.exists():
            return C.fail("文件不存在", "NotFound")

        rel_norm = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel_norm in _CONFIRM_FILES and not bool(args.get("confirm")):
            return C.fail(f"{rel_norm} 是底线文件，要 confirm=true", "NeedConfirm")

        text = p.read_text(encoding="utf-8", errors="replace")
        n = text.count(find)
        if n == 0:
            return C.fail("文件里没找到这段原文，先把原文贴准", "NotFound")
        if n > 1 and not bool(args.get("all")):
            return C.fail(f"这段原文出现了 {n} 次，要么给更长的片段，要么加 all=true", "Ambiguous")

        bak = _backup(p)
        new_text = text.replace(find, repl) if bool(args.get("all")) else text.replace(find, repl, 1)
        p.write_text(new_text, encoding="utf-8")

        if p.suffix.lower() == ".py":
            try:
                py_compile.compile(str(p), doraise=True, cfile=str(p) + ".pyc-check")
                Path(str(p) + ".pyc-check").unlink(missing_ok=True)
            except py_compile.PyCompileError as exc:
                if bak:
                    shutil.copy2(bak, p)
                return C.fail(f"语法错误已回滚：{str(exc)[:300]}", "SyntaxError")

        return C.ok(
            f"改了 {n if bool(args.get('all')) else 1} 处：{rel_norm}"
            + (f"，备份 {Path(bak).name}" if bak else "")
            + "。要重启后端才生效。",
            path=rel_norm, replaced=n if bool(args.get("all")) else 1,
            backup=bak, needs_restart=True,
        )

    return C.fail(
        "action 要给：list（列文件）/ read（读）/ write（整篇写）/ patch（查找替换）",
        "MissingArg: action",
    )


TOOL = {
    "name": "pc.self_update",
    "title": "改我自己的代码",
    "desc": (
        "读取或修改小伴自己的源代码/配置。用于把用户的优化需求直接落地。"
        "action=list 列文件、read 读、write 整篇覆盖、patch 查找替换。"
        "每次写都会自动备份，Python 文件语法错误会自动回滚。"
        "改完要重启后端才生效。安全底线文件（reviewer/auth）需要 confirm=true。"
    ),
    "danger": True,  # 改自己代码，属于危险动作
    "params": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "read", "write", "patch"]},
            "path": {"type": "string", "description": "相对路径，如 core/brain.py"},
            "content": {"type": "string", "description": "write 时给完整新内容"},
            "find": {"type": "string", "description": "patch 时要替换的原文"},
            "replace": {"type": "string", "description": "patch 时替换成什么"},
            "all": {"type": "boolean", "description": "patch 时是否替换全部匹配"},
            "confirm": {"type": "boolean", "description": "改底线文件时必须为 true"},
        },
        "required": ["action"],
    },
    "run": C.guard(run),
}
