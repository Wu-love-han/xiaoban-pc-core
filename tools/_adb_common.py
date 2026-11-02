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


# ---------------------------------------------------------------- UI 结构树（快）
import threading as _threading
import time as _time
import xml.etree.ElementTree as _ET

_ui_cache = {"at": 0.0, "xml": "", "elements": []}
_ui_lock = _threading.RLock()
UI_CACHE_TTL = 1.5  # 秒；同一屏内连续查询命中缓存，0 延迟


def _parse_bounds(b: str):
    """'[x1,y1][x2,y2]' -> (x1,y1,x2,y2)"""
    try:
        nums = re.findall(r"-?\d+", b or "")
        if len(nums) >= 4:
            return tuple(int(n) for n in nums[:4])
    except Exception:
        pass
    return None


def ui_tree(force: bool = False) -> tuple[bool, list[dict] | str]:
    """拿当前界面的结构树（文字 + 坐标 + 可点击），带 1.5 秒缓存。

    比截图快得多：截图要传 100KB+ 图片再让模型看图，
    结构树只是一串文字，模型直接读。
    """
    with _ui_lock:
        if not force and _time.time() - _ui_cache["at"] < UI_CACHE_TTL and _ui_cache["elements"]:
            return True, _ui_cache["elements"]

    ok, msg = device_ready()
    if not ok:
        return False, msg

    try:
        p = subprocess.run([adb_path(), "exec-out", "uiautomator dump /dev/tty"],
                           capture_output=True, timeout=20)
        raw = (p.stdout or b"").decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return False, f"dump 异常：{exc}"

    if "<hierarchy" not in raw:
        return False, "拿不到界面结构（App 可能屏蔽了无障碍，或屏幕未亮）"

    start = raw.find("<hierarchy")
    end = raw.rfind("</hierarchy>")
    if end > 0:
        raw = raw[start:end + len("</hierarchy>")]

    elements: list[dict] = []
    try:
        root = _ET.fromstring(raw)
    except Exception as exc:  # noqa: BLE001
        return False, f"解析失败：{exc}"

    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        rid = (node.get("resource-id") or "").strip()
        cls = (node.get("class") or "").strip()
        if not (text or desc or rid):
            continue
        bounds = _parse_bounds(node.get("bounds") or "")
        if not bounds:
            continue
        x1, y1, x2, y2 = bounds
        if x2 <= x1 or y2 <= y1:
            continue
        elements.append({
            "text": text[:60],
            "desc": desc[:60],
            "id": rid.split("/")[-1][:40] if rid else "",
            "class": cls.split(".")[-1][:24],
            "center": [(x1 + x2) // 2, (y1 + y2) // 2],
            "clickable": node.get("clickable") == "true",
        })

    with _ui_lock:
        _ui_cache.update({"at": _time.time(), "xml": raw, "elements": elements})
    return True, elements


def find_element(keyword: str) -> dict | None:
    """按文字/描述/id 找第一个匹配的元素（不区分大小写）。"""
    kw = (keyword or "").strip().lower()
    if not kw:
        return None
    ok, data = ui_tree()
    if not ok or not isinstance(data, list):
        return None
    # 优先精确匹配，其次包含匹配
    for e in data:
        if kw in (e["text"].lower(), e["desc"].lower(), e["id"].lower()):
            return e
    for e in data:
        if kw in e["text"].lower() or kw in e["desc"].lower() or kw in e["id"].lower():
            return e
    return None
