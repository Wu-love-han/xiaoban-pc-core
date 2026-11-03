"""pc.github_install：从 GitHub 装插件，装完立刻能用。

用户需求：「下载下来，这个软件 ai 能直接识别和使用」
"""

from __future__ import annotations

from typing import Any

from . import _common as C


def run(args: dict, ctx: Any) -> dict:
    spec = str(args.get("repo") or args.get("fullName") or "").strip()
    if not spec:
        return C.fail("要给我 owner/repo，比如 Wu-love-han/pc-core-plugin-demo", "MissingArg: repo")

    tag = str(args.get("tag") or "").strip()
    if tag:
        spec = f"{spec}@{tag.lstrip('v')}"

    try:
        from core import plugins  # noqa: PLC0415

        item = plugins.install(spec)
    except (ValueError, RuntimeError) as exc:
        return C.fail(f"装不了：{exc}", "InstallFailed")
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"装的时候出错：{type(exc).__name__}: {exc}", "InstallError")

    n = int(item.get("tools") or 0)
    if n == 0:
        return C.fail(
            f"装上了「{item.get('name')}」，但它没有 tools/ 目录，所以没有新工具可用。"
            "插件格式要是：plugin.json + tools/*.py（每个文件一个 TOOL 字典）。",
            "NoTools",
        )
    return C.ok(
        f"装好了：{item.get('name')} v{item.get('version')}，新增 {n} 个工具，现在就能用。",
        plugin=item, tools=n,
    )


TOOL = {
    "name": "pc.github_install",
    "title": "从 GitHub 装插件",
    "desc": "把 GitHub 上的插件装进小伴，装完立刻多出新工具。格式要求：仓库里有 plugin.json 和 tools/*.py。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "owner/repo，如 Wu-love-han/pc-core-plugin-demo"},
            "tag": {"type": "string", "description": "指定 Release 版本（可省略，默认最新）"},
        },
        "required": ["repo"],
    },
    "run": C.guard(run),
}
