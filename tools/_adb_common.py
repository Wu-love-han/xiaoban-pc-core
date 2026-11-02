"""ADB 手机控制共用层。

手机通过 USB 或 Tailscale(无线调试) 连上电脑后，直接用 adb 命令操作，
不需要在手机装 Termux。权限底线：
- 只读（截图/读屏/列应用）：直接允许
- 写（点击/滑动/输入/开应用）：允许，但危险词（支付/转账/密码）拦截
- 禁止：卸载应用、清除数据、修改系统设置、拨号、发短信
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

# adb 路径：优先 PATH，其次 phonemcp 自带
_ADB_CANDIDATES = [
    shutil.which("adb"),
    r"C:\Users\Wh987\.phonemcp\platform-tools\adb.exe",
    r"C:\platform-tools\adb.exe",
]

# 危险词：出现在输入/打开目标里就拒绝
DANGER_WORDS = (
    "支付", "付款", "转账", "汇款", "银行卡", "密码", "验证码",
    "登录", "pay", "payment", "transfer", "password", "otp",
)


def adb_path() -> str:
    for p in _ADB_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return "adb"


def _run(args: list[str], timeout: int = 20) -> tuple[int, str, str]:
    """跑 adb 命令，返回 (rc, stdout, stderr)。"""
    cmd = [adb_path()] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", "adb 未安装或路径不对"
    except subprocess.TimeoutExpired:
        return 124, "", "adb 命令超时"


def shell(cmd: str, timeout: int = 20) -> tuple[int, str, str]:
    return _run(["shell", cmd], timeout=timeout)


def device_ready() -> tuple[bool, str]:
    """检查是否有设备在线。"""
    rc, out, err = _run(["devices"])
    if rc != 0:
        return False, err or "adb 执行失败"
    lines = [l for l in out.splitlines()[1:] if l.strip()]
    if not lines:
        return False, "没有手机连接（USB 或无线调试都没连上）"
    if any("\tdevice" in l or " device" in l for l in lines):
        return True, lines[0].strip()
    return False, f"设备未授权：{lines[0].strip()}"


def danger(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in DANGER_WORDS)


def screenshot_bytes() -> tuple[bool, bytes | str]:
    """截图，返回 PNG 字节。"""
    cmd = [adb_path(), "exec-out", "screencap", "-p"]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=25)
        if p.returncode != 0:
            return False, (p.stderr or b"").decode("utf-8", "replace") or "截图失败"
        return True, p.stdout
    except Exception as exc:  # noqa: BLE001
        return False, f"截图异常：{exc}"
