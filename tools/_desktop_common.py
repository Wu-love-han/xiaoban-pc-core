"""桌面控制底层（Windows，纯 ctypes，无第三方依赖）。

为什么需要：AI 能开程序，但开完就干瞪眼——不能点按钮、不能打字，
所以「新建对话并发你好」这种任务永远完不成。这个模块补上这层。

安全：
- 只操作鼠标键盘，不做任何文件/系统改动
- type_text 会拦明显是密码/支付类的文本
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---------------- 常量 ----------------
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002


# ---------------- 结构体 ----------------
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTunion)]


# ---------------- 屏幕 ----------------
def screen_size() -> tuple[int, int]:
    return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def screenshot(path: str, region: tuple[int, int, int, int] | None = None) -> tuple[int, int]:
    """截全屏或指定区域 (left, top, right, bottom)，返回图片尺寸。"""
    from PIL import ImageGrab  # noqa: PLC0415

    img = ImageGrab.grab(bbox=region, all_screens=True) if region else ImageGrab.grab(all_screens=True)
    img.save(path)
    return img.size


def screen_scale() -> float:
    """截图物理像素 / 鼠标逻辑像素 的倍率。

    高 DPI 屏上截图是 2560x1600，但 SetCursorPos 用的是 1280x800。
    不换算的话点哪儿都偏一倍（实测踩过）。
    """
    try:
        from PIL import ImageGrab  # noqa: PLC0415

        img = ImageGrab.grab(all_screens=True)
        pw = img.size[0]
        lw = user32.GetSystemMetrics(0)
        if lw > 0 and pw > 0:
            return pw / lw
    except Exception:  # noqa: BLE001
        pass
    return 1.0


def to_logical(x: int, y: int) -> tuple[int, int]:
    """把「截图里的坐标」换成「鼠标能用的坐标」。"""
    k = screen_scale()
    if k and k != 1.0:
        return int(round(x / k)), int(round(y / k))
    return int(x), int(y)


# ---------------- 窗口 ----------------
def list_windows() -> list[dict]:
    """列出可见且有标题的顶层窗口。"""
    out: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.strip()
        if not title:
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        out.append({
            "hwnd": int(hwnd),
            "title": title,
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
            "minimized": bool(user32.IsIconic(hwnd)),
        })
        return True

    user32.EnumWindows(_cb, 0)
    return out


def find_window(keyword: str) -> dict | None:
    kw = (keyword or "").strip().lower()
    if not kw:
        return None
    wins = list_windows()
    for w in wins:
        if kw == w["title"].lower():
            return w
    for w in wins:
        if kw in w["title"].lower():
            return w
    return None


def focus_window(hwnd: int) -> bool:
    """把窗口带到前台（先还原最小化）。"""
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        return True
    except Exception:  # noqa: BLE001
        return False


def foreground_title() -> str:
    hwnd = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


# ---------------- 鼠标 ----------------
def click(x: int, y: int, button: str = "left", double: bool = False) -> None:
    lx, ly = to_logical(x, y)  # 传进来的可能是截图坐标，先换算
    user32.SetCursorPos(lx, ly)
    time.sleep(0.08)
    down, up = (
        (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
        if button == "right"
        else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    )
    times = 2 if double else 1
    for _ in range(times):
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.08)


def move(x: int, y: int) -> None:
    lx, ly = to_logical(x, y)
    user32.SetCursorPos(lx, ly)


# ---------------- 键盘 ----------------
def _send_input(inp: INPUT) -> None:
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def type_text(text: str, interval: float = 0.01) -> int:
    """逐字输入（支持中文，走 Unicode 注入）。返回输入字数。"""
    n = 0
    for ch in text:
        code = ord(ch)
        if ch == "\n":
            press_keys("enter")
            n += 1
            continue
        # 下压
        down = INPUT(type=INPUT_KEYBOARD)
        down.union.ki = KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None)
        _send_input(down)
        # 抬起
        up = INPUT(type=INPUT_KEYBOARD)
        up.union.ki = KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)
        _send_input(up)
        n += 1
        if interval:
            time.sleep(interval)
    return n


# 常用键的虚拟键码
_VK = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
    "win": 0x5B, "cmd": 0x5B,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
}


def _vk_of(name: str) -> int | None:
    k = (name or "").strip().lower()
    if k in _VK:
        return _VK[k]
    if len(k) == 1:
        return ord(k.upper())
    return None


def press_keys(combo: str) -> bool:
    """按键组合，如 'enter'、'ctrl+v'、'ctrl+shift+s'。"""
    parts = [p.strip().lower() for p in (combo or "").split("+") if p.strip()]
    if not parts:
        return False
    codes = []
    for p in parts:
        vk = _vk_of(p)
        if vk is None:
            return False
        codes.append(vk)

    for vk in codes:  # 依次按下
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.02)
    for vk in reversed(codes):  # 逆序抬起
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.02)
    return True


# 明显不该由 AI 输入的内容
_SECRET_WORDS = ("密码", "支付密码", "验证码", "转账", "银行卡", "身份证号", "password", "passwd", "otp")


def looks_secret(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in _SECRET_WORDS)


# 支付/收银台类界面：AI 绝对不能在这里点击或打字（用户的红线）
_PAYMENT_WORDS = (
    "支付", "付款", "收银台", "银行卡", "卡号", "有效期", "安全码", "cvv",
    "checkout", "payment", "pay now", "billing", "银行卡号", "信用卡",
    "apple pay", "google pay", "支付宝", "微信支付", "转账",
)


def looks_like_payment(title: str = "") -> bool:
    """当前窗口是不是支付/收银台界面。"""
    t = (title or foreground_title() or "").lower()
    return any(w in t for w in _PAYMENT_WORDS)
