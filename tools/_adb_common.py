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
# 真正的红线：只有「钱」和「凭据」这两类。
# 用户要求放宽（「给他的权限可以大一点」），所以去掉了「登录」这种过宽的词
# —— 让人工智能连「登录」两个字都不能输入，属于过度限制。
DANGER_WORDS = (
    "支付", "付款", "转账", "汇款", "银行卡", "信用卡", "付款码", "收款码",
    "密码", "验证码", "短信验证码",
    "pay now", "payment", "transfer money", "password", "passwd", "otp", "cvv",
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


# App 是否可用（避免每次都等超时）
_app_probe = {"ok": False, "at": 0.0}
_APP_PROBE_TTL = 20.0  # 秒


def _app_usable() -> bool:
    now = _time.time()
    if now - _app_probe["at"] < _APP_PROBE_TTL:
        return _app_probe["ok"]
    ok = app_ready()
    _app_probe["at"] = now
    _app_probe["ok"] = ok
    return ok


def ui_tree(force: bool = False) -> tuple[bool, list[dict] | str]:
    """拿当前界面的结构树（文字 + 坐标 + 可点击），带 1.5 秒缓存。

    优先走手机 App 的无障碍服务（约 0.4 秒），
    拿不到才回落 uiautomator dump（约 2.3 秒）。
    比截图快得多：截图要传 100KB+ 图片再让模型看图。
    """
    with _ui_lock:
        if not force and _time.time() - _ui_cache["at"] < UI_CACHE_TTL and _ui_cache["elements"]:
            return True, _ui_cache["elements"]

    # ---- 快路径：手机 App 无障碍服务 ----
    if _app_usable():
        ok_app, data_app = app_tree()
        if ok_app and isinstance(data_app, list) and data_app:
            with _ui_lock:
                _ui_cache.update({"at": _time.time(), "xml": "", "elements": data_app})
            return True, data_app
        # App 掉线了，标记一下，下次直接走慢路径
        if not ok_app:
            _app_probe["ok"] = False

    # ---- 慢路径：uiautomator dump ----
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


# ================================================================
# 手机 App 本地能力服务（v2 App 内置，端口 9123）
# 比 uiautomator dump 快 6 倍，而且能直接点节点、直接写输入框
# ================================================================

_app_base_cache: dict = {"url": "", "at": 0.0}


def _phone_conf() -> dict:
    try:
        from core import config as cfg_mod  # noqa: PLC0415

        return (cfg_mod.load().get("providers") or {}).get("phone") or {}
    except Exception:  # noqa: BLE001
        return {}


def _app_candidates() -> list[str]:
    conf = _phone_conf()
    urls = conf.get("cap_urls") or []
    if urls:
        return [str(u).rstrip("/") for u in urls]
    return ["http://100.115.152.111:9123", "http://172.30.188.163:9123"]


def _app_token() -> str:
    return str(_phone_conf().get("token") or "")


def _app_request(path: str, method: str = "GET", body: dict | None = None,
                 timeout: float | None = None) -> tuple[bool, dict]:
    """请求手机 App 的本地服务，自动在候选地址里找一个能用的。"""
    import json as _json
    import urllib.error
    import urllib.request

    conf = _phone_conf()
    if timeout is None:
        timeout = float(conf.get("timeout_s") or 8)
    token = _app_token()

    # 上次成功的地址优先
    bases = list(_app_candidates())
    last = _app_base_cache.get("url")
    if last and last in bases:
        bases.remove(last)
        bases.insert(0, last)

    payload = _json.dumps(body or {}, ensure_ascii=False).encode("utf-8") if method == "POST" else None
    last_err = ""

    for base in bases:
        try:
            req = urllib.request.Request(base + path, data=payload, method=method)
            req.add_header("Content-Type", "application/json")
            if token:
                req.add_header("X-PC-Token", token)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = _json.loads(resp.read().decode("utf-8", "replace"))
            _app_base_cache["url"] = base
            return True, data
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
    return False, {"ok": False, "error": last_err or "连不上手机 App"}


def app_available() -> bool:
    """手机 App 的本地服务在不在。"""
    ok, data = _app_request("/ping")
    return bool(ok and data.get("ok"))


def app_ready() -> bool:
    """App 在，且无障碍服务已开。"""
    ok, data = _app_request("/ping")
    return bool(ok and data.get("ok") and data.get("accessibility"))


def app_tree(limit: int = 200) -> tuple[bool, list[dict] | str]:
    """从 App 拿实时界面树（快）。返回和 ui_tree 一样结构的元素列表。"""
    ok, data = _app_request(f"/tree?limit={int(limit)}")
    if not ok:
        return False, str(data.get("error") or "连不上手机 App")
    if not data.get("ok"):
        return False, str(data.get("error") or "App 返回失败")

    elements = []
    for e in data.get("elements") or []:
        center = e.get("center") or [0, 0]
        elements.append({
            "text": (e.get("text") or "")[:60],
            "desc": (e.get("desc") or "")[:60],
            "id": (e.get("id") or "")[:40],
            "class": (e.get("cls") or "")[:24],
            "center": [int(center[0]), int(center[1])],
            "clickable": bool(e.get("clickable")),
            "editable": bool(e.get("editable")),
        })
    return True, elements


def app_click_text(text: str) -> tuple[bool, str]:
    # 点击可能触发新页面启动，给宽一点
    ok, data = _app_request("/click", method="POST", body={"text": text}, timeout=20)
    if not ok:
        return False, str(data.get("error") or "连不上手机 App")
    if data.get("ok"):
        return True, f"点了「{text}」"
    return False, str(data.get("error") or "点击失败")


def app_click_xy(x: int, y: int) -> tuple[bool, str]:
    ok, data = _app_request("/click", method="POST", body={"x": int(x), "y": int(y)})
    if not ok:
        return False, str(data.get("error") or "连不上手机 App")
    return (True, f"点了 ({x},{y})") if data.get("ok") else (False, str(data.get("error") or "点击失败"))


def app_type(text: str) -> tuple[bool, str]:
    ok, data = _app_request("/type", method="POST", body={"text": text})
    if not ok:
        return False, str(data.get("error") or "连不上手机 App")
    return (True, f"写入了 {data.get('count', len(text))} 个字") if data.get("ok") else (False, str(data.get("error") or "写入失败"))


def app_key(name: str) -> tuple[bool, str]:
    ok, data = _app_request("/key", method="POST", body={"name": name})
    if not ok:
        return False, str(data.get("error") or "连不上手机 App")
    return (True, f"按了 {name}") if data.get("ok") else (False, str(data.get("error") or "按键失败"))


# ---------------------------------------------------------------- 手机 shell（Shizuku）

def app_shell_info() -> dict:
    ok, data = _app_request("/shell/info")
    return data if ok else {"ok": False, "error": str(data.get("error") or "")}


def app_shell(cmd: str, timeout_s: int = 15) -> tuple[bool, str, str]:
    """在手机上跑命令。level=shizuku 时是 shell 权限（uid 2000）。"""
    ok, data = _app_request("/shell", method="POST",
                            body={"cmd": cmd, "timeout": int(timeout_s) * 1000},
                            timeout=float(timeout_s) + 10)
    if not ok:
        return False, str(data.get("error") or "连不上手机 App"), ""
    return True, str(data.get("output") or ""), str(data.get("level") or "")


# ---------------------------------------------------------------- App 端口（远程可用）

def app_open_app(pkg: str) -> tuple[bool, str]:
    ok, data = _app_request("/open_app", method="POST", body={"package": pkg}, timeout=20)
    if not ok:
        return False, str(data.get("error") or "连不上手机 App")
    return (True, f"打开了 {pkg}") if data.get("ok") else (False, str(data.get("error") or "打开失败"))


def app_foreground() -> tuple[bool, str]:
    ok, data = _app_request("/foreground")
    if not ok:
        return False, str(data.get("error") or "连不上手机 App")
    return True, str(data.get("package") or "")


def app_list_apps() -> tuple[bool, list[dict]]:
    ok, data = _app_request("/apps", timeout=25)
    if not ok or not data.get("ok"):
        return False, []
    return True, data.get("apps") or []
