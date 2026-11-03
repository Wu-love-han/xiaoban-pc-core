"""phone.shell：在手机上执行命令（借 Shizuku 拿 shell 权限，无需 root）。"""

from __future__ import annotations

from typing import Any

from . import _adb_common as A
from . import _common as C


def run(args: dict, ctx: Any) -> dict:
    cmd = str(args.get("command") or args.get("cmd") or "").strip()
    if not cmd:
        return C.fail("要给一条命令，比如 `id`、`pm list packages -3`、`dumpsys battery`。", "MissingArg: command")

    # 危险命令拦截（跟 PC 的 shell 一个底线）
    low = cmd.lower()
    for bad in ("rm -rf /", "mkfs", "dd if=", "format ", "> /dev/block", "reboot -p"):
        if bad in low:
            return C.fail("这条命令太危险，不执行。", "Blocked:Danger")

    info = A.app_shell_info()
    level = info.get("level", "?")
    if level == "app":
        return C.fail(
            "手机 App 现在只有自己的权限（没连上 Shizuku）。"
            "要系统级操作，请打开 Shizuku App 并授权「小伴」。",
            "NoShizuku",
        )

    ok, output, real_level = A.app_shell(cmd, timeout_s=int(args.get("timeout") or 15))
    if not ok:
        return C.fail(f"执行失败：{output}", "ShellFailed")
    return C.ok(output[:2000], level=real_level, command=cmd)


TOOL = {
    "name": "phone.shell",
    "title": "手机执行命令",
    "desc": "在手机上跑 shell 命令（借 Shizuku 拿 shell 权限，不需要 root）。能装应用、改设置、读系统信息、dumpsys 等。危险命令会被拦。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令，如 id / pm list packages -3 / dumpsys battery"},
            "timeout": {"type": "integer", "description": "超时秒数，默认 15"},
        },
        "required": ["command"],
    },
    "run": C.guard(run),
}
