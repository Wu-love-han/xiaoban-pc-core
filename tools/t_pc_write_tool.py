"""pc.write_tool：AI 自己写一个新工具，写完立刻能用。

为什么要有：
  固定 60 个工具永远不够用。遇到没工具的场景，AI 应该能自己造一个，
  而不是干等着人来写。DSH 也是这个思路（工具按需扩展）。

安全：
  - 只允许写到 plugins/selfmade/tools/（不碰核心代码）
  - 写之前先语法检查，错了不落盘
  - 写完必须能加载成功才算数，否则回滚
  - 工具名必须以 self. 开头（一眼看出是自造的）
"""

from __future__ import annotations

import ast
import importlib
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from . import _common as C

SELFMADE = "selfmade"
MAX_CODE = 20000


def _plugins_root() -> Path:
    from core.paths import ROOT  # noqa: PLC0415

    return ROOT / "plugins" / SELFMADE


def _tools_dir() -> Path:
    return _plugins_root() / "tools"


def _ensure() -> None:
    d = _tools_dir()
    d.mkdir(parents=True, exist_ok=True)
    pj = _plugins_root() / "plugin.json"
    if not pj.exists():
        pj.write_text(
            '{\n  "id": "selfmade",\n  "name": "自造工具",\n  "version": "0.1.0",\n'
            '  "description": "AI 自己写的工具",\n  "author": "xiaoban"\n}\n',
            encoding="utf-8",
        )


def _reload() -> tuple[bool, str]:
    """让新工具生效。"""
    try:
        from core.toolbase import load_all, registry  # noqa: PLC0415
        from core.paths import ROOT  # noqa: PLC0415

        # 清掉旧模块缓存（插件模块名是 pccore_plugin_<id>_<stem>）
        for name in list(sys.modules):
            if name.startswith(f"pccore_plugin_{SELFMADE}_"):
                del sys.modules[name]
        from core import plugins as P  # noqa: PLC0415

        n = P.reload_plugin_tools(SELFMADE)
        return True, f"重载了 {n} 个自造工具，当前共 {len(registry.schemas())} 个工具"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def run(args: dict, ctx: Any) -> dict:
    action = str(args.get("action") or "create").strip().lower()

    if action == "list":
        d = _tools_dir()
        if not d.exists():
            return C.ok("还没造过工具。", items=[])
        files = sorted(p.name for p in d.glob("t_*.py"))
        return C.ok(
            f"自造工具 {len(files)} 个：\n" + "\n".join(f"  - {f}" for f in files),
            items=files,
        )

    if action == "delete":
        name = str(args.get("name") or "").strip()
        if not name:
            return C.fail("要删哪个？给工具名（如 self.excel）", "MissingArg")
        fname = "t_" + name.replace("self.", "").replace(".", "_") + ".py"
        p = _tools_dir() / fname
        if not p.exists():
            return C.fail(f"没有 {fname}", "NotFound")
        try:
            p.unlink()
        except Exception as exc:  # noqa: BLE001
            return C.fail(f"删不掉：{exc}", "DeleteFailed")
        ok, msg = _reload()
        return C.ok(f"删了 {fname}。{msg}") if ok else C.fail(f"删了但重载失败：{msg}", "ReloadFailed")

    # ---------- create ----------
    name = str(args.get("name") or "").strip()
    code = str(args.get("code") or "")

    if not name:
        return C.fail("要给工具名，比如 self.excel", "MissingArg: name")
    if not name.startswith("self."):
        return C.fail(
            "工具名必须以 self. 开头（一眼看出是自造的），比如 self.excel",
            "BadName",
        )
    if not code.strip():
        return C.fail("要给代码", "MissingArg: code")
    if len(code) > MAX_CODE:
        return C.fail(f"代码太长（{MAX_CODE} 字上限）", "TooLong")

    # 1) 语法检查
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return C.fail(
            f"语法错误（第 {exc.lineno} 行）：{exc.msg}\n改好再来。",
            "SyntaxError",
        )

    # 2) 必须导出 TOOL
    has_tool = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "TOOL":
                    has_tool = True
    if not has_tool:
        return C.fail(
            "代码里必须有 TOOL 字典（name/title/desc/params/run）。\n"
            "格式看 tools/t_pc_run.py 的末尾。",
            "NoToolDict",
        )

    # 3) 写文件
    _ensure()
    safe = name.replace("self.", "").replace(".", "_")
    fname = f"t_self_{safe}.py"
    target = _tools_dir() / fname
    backup = None
    if target.exists():
        backup = target.with_suffix(".py.bak-" + str(int(time.time())))
        shutil.copy2(target, backup)

    try:
        target.write_text(code, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"写文件失败：{exc}", "WriteFailed")

    # 4) 试着加载，失败就回滚
    ok, msg = _reload()
    if not ok:
        try:
            if backup:
                shutil.copy2(backup, target)
            else:
                target.unlink()
        except Exception:  # noqa: BLE001
            pass
        _reload()
        return C.fail(
            f"工具加载失败，已回滚。\n错误：{msg}\n"
            "常见原因：TOOL 里缺字段、run 签名不对、import 了没装的库。",
            "LoadFailed",
        )

    # 5) 确认真的注册上了
    try:
        from core.toolbase import registry  # noqa: PLC0415

        names = [s.get("function", {}).get("name") for s in registry.schemas()]
        # 注册表把点转下划线：self.hello → self_hello
        wire = name.replace(".", "_")
        registered = name in names or wire in names
    except Exception:  # noqa: BLE001
        registered = False

    if not registered:
        try:
            if backup:
                shutil.copy2(backup, target)
            else:
                target.unlink()
        except Exception:  # noqa: BLE001
            pass
        _reload()
        return C.fail(
            f"文件写了但工具没注册上（TOOL['name'] 是不是写成别的了？应该是 {name}）。已回滚。",
            "NotRegistered",
        )

    return C.ok(
        f"工具造好了：{name}\n"
        f"  文件：{target}\n"
        f"  {msg}\n"
        f"现在就能调 {name} 了。",
        name=name, file=str(target),
    )


TOOL = {
    "name": "pc.write_tool",
    "title": "造一个新工具",
    "desc": (
        "自己写一个新工具，写完立刻能用。遇到没有工具的场景就用这个。\n"
        "代码要求：必须有 TOOL = {name, title, desc, danger, params, run}，"
        "name 必须以 self. 开头。run(args, ctx) 返回 C.ok(...) 或 C.fail(...)。\n"
        "action=list 看造过哪些，action=delete 删掉。"
    ),
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "list", "delete"], "description": "create=造（默认），list=看，delete=删"},
            "name": {"type": "string", "description": "工具名，必须 self. 开头，如 self.excel"},
            "code": {"type": "string", "description": "完整 Python 代码（含 TOOL 字典）"},
        },
        "required": ["action"],
    },
    "run": C.guard(run),
}
