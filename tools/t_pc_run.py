"""pc.run：跑任意命令（分级审批，取代只读白名单的 pc.shell）。

为什么要有这个：
  pc.shell 只允许 75 条只读命令，AI 只能"看"不能"做"——
  装不了插件、改不了配置、做不了实际任务。DSH 的 bash 能跑任何命令，
  差距就在这。这个工具把能力放开，但用分级审批兜住风险。

分级：
  0 只读        → 直接跑（dir/type/netstat/git status…）
  1 低危写      → 直接跑（在项目目录/临时目录里写、建目录）
  2 中危        → 要用户确认（装软件、删文件、改配置、结束进程）
  3 高危        → 要用户确认 + 先备份（系统目录、注册表、服务）
  红线          → 永久拒绝（支付、密码、验证码、冒充他人）

用户可以在控制台给「临时免确认」，1 小时内不用反复问。
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from . import _common as C

TIMEOUT_DEFAULT = 60
TIMEOUT_MAX = 300
MAX_BYTES = 60000

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ---------------------------------------------------------------- 红线（永久禁止）
RED_LINES = (
    # 钱
    "转账", "汇款", "支付", "付款", "银行卡", "信用卡", "花呗", "白条",
    "transfer money", "wire transfer", "paypal.me",
    # 凭据
    "password", "passwd", "密码", "验证码", "otp", "cvv",
    "keychain", "credential", "secret_key",
    # 冒充
    "冒充", "impersonate",
)

# ---------------------------------------------------------------- 分级规则
# 只读命令前缀（等级 0）
READ_ONLY = (
    "dir", "ls", "type", "cat", "more", "head", "tail", "find", "findstr", "grep",
    "where", "which", "echo", "ver", "whoami", "hostname", "date", "time",
    "systeminfo", "tasklist", "netstat", "ipconfig", "ping", "nslookup", "tracert",
    "tree", "vol", "chcp", "set", "path", "cd", "pwd", "git status", "git log",
    "git diff", "git branch", "git remote", "python --version", "node -v", "pip list",
    "npm list", "wmic os", "sc query", "reg query", "dumpsys", "getprop",
    "adb devices", "adb shell getprop", "adb shell dumpsys",
)

# 等级 2：中危（装、删、改、杀）
MEDIUM = (
    "pip install", "pip uninstall", "npm install", "npm uninstall", "winget",
    "choco", "scoop", "rm ", "del ", "rmdir", "rd ", "move ", "mv ",
    "copy ", "cp ", "xcopy", "robocopy", "ren ", "rename ",
    "taskkill", "stop-process", "net stop", "sc stop", "sc delete",
    "setx", "reg add", "reg delete", "reg import",
    "git reset", "git checkout", "git clean", "git push", "git commit",
    "schtasks", "nssm", "netsh", "icacls", "takeown", "attrib",
)

# 等级 3：高危（系统目录、服务、驱动、引导）
HIGH = (
    "format", "diskpart", "bcdedit", "bootrec", "sfc", "dism",
    "regedit", "gpedit", "services.msc", "devmgmt",
    "shutdown", "restart-computer", "stop-computer",
    "system32", "program files", "\\windows\\",
)

# 危险字符：允许，但要提示（这些是正常的 shell 语法，不该像 pc.shell 那样一刀切）
_SHELL_META = re.compile(r"[&;<>|`$]")


def _first_word(cmd: str) -> str:
    s = cmd.strip().lstrip("@")
    return s.split(" ", 1)[0].lower() if s else ""


def _match_prefix(cmd: str, prefixes: tuple) -> str | None:
    low = " ".join(cmd.strip().lower().split())
    for p in prefixes:
        p2 = p.strip().lower()
        if low == p2 or low.startswith(p2 + " "):
            return p2
    return None


def classify(cmd: str) -> tuple[int, str]:
    """返回 (等级, 理由)。等级 4 = 红线。"""
    low = " ".join(cmd.strip().lower().split())
    if not low:
        return 0, "空命令"

    for w in RED_LINES:
        if w in low:
            return 4, f"命中红线「{w}」"

    if _match_prefix(cmd, HIGH):
        return 3, "高危操作（系统目录/服务/引导）"
    if _match_prefix(cmd, MEDIUM):
        return 2, "中危操作（安装/删除/修改/结束进程）"

    # 写文件的重定向——必须在只读判断之前（echo x > a.txt 是写文件，不是只读）
    if re.search(r">\s*[^\s|]", cmd):
        return 2, "会写文件（重定向）"

    if _match_prefix(cmd, READ_ONLY):
        return 0, "只读命令"

    return 1, "未知命令，按低危处理"


def _run_proc(cmd: str, cwd: str | None, timeout: int) -> dict:
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, shell=True, cwd=cwd or None,
            capture_output=True, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("gbk", "replace")
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "out": out[:MAX_BYTES],
            "err": err[:MAX_BYTES],
            "ms": int((time.time() - t0) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "out": "", "err": f"超时（{timeout} 秒）",
                "ms": int((time.time() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "code": -1, "out": "", "err": f"{type(exc).__name__}: {exc}",
                "ms": int((time.time() - t0) * 1000)}


def _check_grant(level: int) -> tuple[bool, str]:
    """查有没有用户给的临时免确认。"""
    try:
        from core import consent  # noqa: PLC0415

        st = consent.state()
        grant = st.get("grant") or {}
        if grant.get("active") and int(grant.get("max_level") or 0) >= level:
            left = int(grant.get("until_ms") or 0) - int(time.time() * 1000)
            if left > 0:
                return True, f"用户已授权等级≤{grant.get('max_level')}（还剩 {left//60000} 分钟）"
    except Exception:  # noqa: BLE001
        pass
    return False, ""


def run(args: dict, ctx: Any) -> dict:
    cmd = str(args.get("cmd") or args.get("command") or "").strip()
    if not cmd:
        return C.fail("要跑什么命令？", "MissingArg: cmd")
    if len(cmd) > 4000:
        return C.fail("命令太长（4000 字上限）", "TooLong")

    try:
        timeout = int(args.get("timeout") or TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        timeout = TIMEOUT_DEFAULT
    timeout = max(5, min(TIMEOUT_MAX, timeout))

    cwd = str(args.get("cwd") or "").strip() or None
    if cwd and not Path(cwd).is_dir():
        return C.fail(f"工作目录不存在：{cwd}", "BadCwd")

    level, why = classify(cmd)

    # 红线：永久拒绝
    if level == 4:
        return C.fail(
            f"这条命令碰到红线了：{why}\n"
            "钱和凭据相关的事，我永远不碰，你自己来。",
            "RedLine",
        )

    # 等级 2/3：要确认（除非用户给了临时授权）
    if level >= 2:
        granted, gmsg = _check_grant(level)
        if not granted:
            if bool(args.get("dry_run")):
                return C.ok(
                    f"[预演] 等级 {level}：{why}\n命令：{cmd}\n"
                    "真正跑的话会先问你确认。",
                    level=level, need_consent=True, preview=True,
                )
            try:
                from core import consent  # noqa: PLC0415

                item = consent.create(
                    kind="run_cmd",
                    target=cmd[:200],
                    detail=f"等级 {level}：{why}",
                )
                cid = item.get("id") or ""
            except Exception as exc:  # noqa: BLE001
                return C.fail(f"发确认请求失败：{exc}", "ConsentFailed")

            # 等用户批（最多 5 分钟）
            deadline = time.time() + 300
            while time.time() < deadline:
                time.sleep(2)
                try:
                    cur = consent.get(cid)
                except Exception:  # noqa: BLE001
                    break
                if not cur:
                    break
                if cur.get("status") == "approved":
                    try:
                        consent.consume(cid)
                    except Exception:  # noqa: BLE001
                        pass
                    break
                if cur.get("status") in ("denied", "expired"):
                    return C.fail(
                        f"用户没同意这条命令（{why}）。{cmd}",
                        "Denied",
                    )
            else:
                return C.fail(
                    f"等确认超时了（5 分钟）。命令：{cmd}\n"
                    "可以在控制台批准，或者告诉我换个做法。",
                    "ConsentTimeout",
                )

    # 等级 3：先备份能备份的
    if level == 3:
        try:
            from tools import _protect as P  # noqa: PLC0415

            for token in cmd.split():
                t = token.strip('"\'')
                if os.path.isabs(t) and os.path.isfile(t):
                    P.backup(t)
        except Exception:  # noqa: BLE001
            pass

    res = _run_proc(cmd, cwd, timeout)
    body = res["out"] or ""
    if res["err"]:
        body = (body + "\n[stderr]\n" + res["err"]).strip()

    head = f"[等级 {level}｜{why}｜退出码 {res['code']}｜{res['ms']}ms]"
    if res["ok"]:
        return C.ok(f"{head}\n{body or '(无输出)'}", level=level, code=res["code"], ms=res["ms"])
    return C.fail(f"{head}\n{body or '(无输出)'}", "NonZeroExit")


TOOL = {
    "name": "pc.run",
    "title": "跑命令（能做任何事）",
    "desc": (
        "在电脑上跑任意命令。只读的直接跑，装软件/删文件/改配置会先问用户确认。"
        "这是你干活的主要工具——装插件、改配置、处理文件、跑脚本都用它。"
        "红线（钱、密码、验证码）永远拒绝。"
        "dry_run=true 可以先看会怎么判级，不真跑。"
    ),
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "cmd": {"type": "string", "description": "要跑的命令（cmd/PowerShell 语法都行）"},
            "cwd": {"type": "string", "description": "工作目录（省略=当前目录）"},
            "timeout": {"type": "integer", "description": "超时秒数，默认 60，最多 300"},
            "dry_run": {"type": "boolean", "description": "true=只判级不执行"},
        },
        "required": ["cmd"],
    },
    "run": C.guard(run),
}
