"""pc.shell：跑一条白名单里的只读命令（危险动作，需要人格先问一句）。

安全模型（这是整个工具层唯一执行外部命令的地方，所以写清楚）：

1. **前缀白名单**：命令必须（去掉多余空白后）以 config.tools.shell_whitelist
   里的某一项开头，否则直接拒绝。白名单在 core/paths.py 的 DEFAULT_CONFIG 里。
2. **禁止命令串联**：即使前缀合法，也不许出现 `& | ; > < 反引号 $(` 这类
   能把一条命令变成多条 / 能重定向写文件的字符。`dir & del x` 前缀也是 "dir"，
   只靠前缀拦不住，必须再拦这层。
3. **禁绝对路径开头**：`C:\\Windows\\System32\\x.exe` 这种不能靠白名单放行。
4. **不喂 stdin**（DEVNULL），否则 `time`、`pause` 这类交互命令会把工具挂死。
5. **20 秒超时**，超时就杀掉进程树并回人话。

输出同时给 stdout 和 stderr——很多只读命令（如 git status）把有用信息写 stderr。
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
from typing import Any

from . import _common as C

TIMEOUT_S = 20
MAX_BYTES = 6000  # 先留一点，output 最后还会被压到 400 字

# 命令串联 / 重定向 / 子命令替换：白名单是前缀匹配，不拦这些等于没拦
_FORBIDDEN = re.compile(r"[&|;<>`\n\r]|\$\(")
# 通配符不算危险，但会撑爆输出；允许，交给输出截断处理
_WS = re.compile(r"\s+")


def _normalize(cmd: str) -> str:
    return _WS.sub(" ", cmd.strip())


def _match_whitelist(cmd: str, whitelist: list[str]) -> str | None:
    """返回命中的白名单项；没命中返回 None。

    比较用大小写不敏感的前缀，且要求后面是结尾或空格——
    否则 "dirx" 会被 "dir" 误放行。
    """
    low = cmd.lower()
    for item in whitelist:
        it = _normalize(str(item)).lower()
        if not it:
            continue
        if low == it or low.startswith(it + " "):
            return str(item)
    return None


def _decode(b: bytes | None) -> str:
    if not b:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return b.decode("utf-8", errors="replace")


def run(args: dict, ctx: Any) -> dict:
    raw = str(args.get("command") or args.get("cmd") or "")
    if not raw.strip():
        return C.fail("要跑哪条命令呢？command 是空的。", "MissingArg: command")

    cmd = _normalize(raw)
    if len(cmd) > 500:
        return C.fail("命令太长了（超过 500 字），我不跑。", "CommandTooLong")

    whitelist = C.cfg_get(ctx, "tools.shell_whitelist", []) or []
    if not isinstance(whitelist, list):
        whitelist = []

    hit = _match_whitelist(cmd, whitelist)
    if hit is None:
        sample = "、".join(str(x) for x in whitelist[:8])
        return C.fail(
            f"「{cmd}」不在白名单里，我不跑。我现在只会这些开头的只读命令：{sample}…",
            "NotWhitelisted",
        )

    bad = _FORBIDDEN.search(cmd)
    if bad:
        return C.fail(
            f"这条命令里有「{bad.group(0)}」，能把一条命令变成多条或者改文件，"
            f"就算开头是「{hit}」我也不跑。要做得拆成单独的命令。",
            "CommandChaining",
        )

    # 绝对路径 / 带目录的命令不许走白名单（防止 C:\...\evil.exe）
    first = cmd.split(" ", 1)[0]
    if os.path.isabs(first) or (len(first) > 1 and first[1] == ":"):
        return C.fail("不要用绝对路径直接跑程序，白名单只管命令名。", "AbsolutePathBlocked")

    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            timeout=TIMEOUT_S,
            encoding=None,          # 自己解码：cmd 输出常是 GBK
            stdin=subprocess.DEVNULL,
            cwd=str(C.workspace(ctx)),
        )
    except subprocess.TimeoutExpired:
        return C.fail(f"这条命令跑了 {TIMEOUT_S} 秒还没完，我掐了。", "Timeout")
    except FileNotFoundError:
        return C.fail(f"找不到这个命令：{first}", "FileNotFound")
    except OSError as exc:
        return C.fail(f"命令没跑起来：{exc.strerror or exc}", f"OSError: {exc}")

    out = _decode(proc.stdout)[:MAX_BYTES].strip()
    err = _decode(proc.stderr)[:1000].strip()
    code = proc.returncode

    body = out or "(没有任何输出)"
    if err:
        body += f"\n[stderr] {err[:300]}"

    head = f"`{cmd}` 退出码 {code}"
    if code != 0:
        return {
            "ok": False,
            "output": C.clip(f"{head}\n{body}"),
            "error": f"ExitCode: {code}",
            "data": {"command": cmd, "code": code, "stdout": out, "stderr": err},
        }

    return C.ok(
        f"{head}\n{body}",
        command=cmd,
        code=code,
        stdout=out,
        stderr=err,
        shell=platform.system(),
    )


TOOL = {
    "name": "pc.shell",
    "title": "跑只读命令",
    "desc": "执行一条白名单内的只读命令（dir/ls/type/echo/whoami/hostname/tasklist/ipconfig/systeminfo/date/git status/nvidia-smi/python --version 等），20 秒超时。不能串联命令、不能重定向。",
    "danger": True,
    "params": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的命令，必须以上述白名单里的某一项开头，例如：dir E:\\WH",
            }
        },
        "required": ["command"],
    },
    "run": C.guard(run),
}
