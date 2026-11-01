"""设备层的共用部分：模拟状态机 + 旧后端调用。

下划线开头，不会被 registry 当成工具。

设计：
- `config.device.simulate = true` → 用本进程内存里的 dict 存状态，**真的记住**，
  同一进程内再查能看到上次改的结果（不是每次返回假的固定值）。
- `simulate = false` → 调 `config.device.backend_url` 的老后端，HTTP 失败就报人话，
  不抛异常。老后端的接口形状未知，所以路径按最常见的 REST 约定写，失败信息写清楚，
  方便以后对着真后端改。

设备模型（首批三个，跟契约 6.3 一致：灯 / 电视 / 风扇）：
    light  灯    on/off，可带 brightness(0-100)
    tv     电视  on/off，可带 channel
    fan    风扇  on/off，可带 speed(1-3)
"""

from __future__ import annotations

import threading
from typing import Any

from . import _common as C

# 同一个进程内的模拟状态。加锁是因为服务端是异步 + 线程池混跑。
_lock = threading.RLock()

_DEFAULT_DEVICES: dict[str, dict] = {
    "light": {"label": "客厅灯", "kind": "light", "on": False, "brightness": 80},
    "tv": {"label": "电视", "kind": "tv", "on": False, "channel": 1},
    "fan": {"label": "风扇", "kind": "fan", "on": False, "speed": 2},
}

# 进程内模拟状态（首次访问时从默认值深拷贝）
_state: dict[str, dict] | None = None

# 说话队列（模拟时只留最近 20 条，够自测和排查用）
_speech: list[str] = []
_SPEECH_KEEP = 20

# 动作别名：模型可能说「打开/开/on/开启」，统一成 on / off / set
_ON_WORDS = {
    "on", "open", "turn_on", "start", "enable",
    "开", "打开", "开启", "启动", "亮",
}
_OFF_WORDS = {
    "off", "close", "turn_off", "stop", "disable",
    "关", "关闭", "关掉", "停止", "灭",
}
_TOGGLE_WORDS = {"toggle", "switch", "切换", "翻转"}


def _ensure_state() -> dict[str, dict]:
    global _state
    with _lock:
        if _state is None:
            _state = {k: dict(v) for k, v in _DEFAULT_DEVICES.items()}
        return _state


def normalize_action(raw: Any) -> str:
    """把五花八门的动作词归一成 on / off / toggle / set。"""
    s = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not s:
        return ""
    if s in _ON_WORDS:
        return "on"
    if s in _OFF_WORDS:
        return "off"
    if s in _TOGGLE_WORDS:
        return "toggle"
    # 没归到开关类的，原样交回去（可能是 brightness=60 这种设值动作）
    return s


def normalize_name(raw: Any) -> str:
    """设备名归一：中文别名 → 内部 key。"""
    s = str(raw or "").strip().lower()
    alias = {
        "灯": "light", "电灯": "light", "台灯": "light", "客厅灯": "light",
        "电视": "tv", "电视机": "tv", "television": "tv",
        "风扇": "fan", "电扇": "fan", "空调扇": "fan", "fan": "fan",
    }
    return alias.get(s, s)


def list_devices() -> list[dict]:
    """当前可控设备清单（模拟模式下是真实状态）。"""
    st = _ensure_state()
    with _lock:
        return [
            {
                "name": k,
                "label": v.get("label") or k,
                "kind": v.get("kind") or k,
                "on": bool(v.get("on")),
                "state": {kk: vv for kk, vv in v.items() if kk not in ("label", "kind", "on")},
            }
            for k, v in st.items()
        ]


def describe(v: dict) -> str:
    """把一台设备压成一句话：客厅灯 开 亮度80。"""
    parts = [v.get("label") or "设备", "开" if v.get("on") else "关"]
    for k, val in v.items():
        if k in ("label", "kind", "on"):
            continue
        parts.append(f"{k}{val}")
    return " ".join(parts)


def apply_sim(name: str, action: str, value: Any) -> tuple[bool, str]:
    """在模拟状态上执行一次控制，返回 (ok, 人话)。"""
    st = _ensure_state()
    with _lock:
        dev = st.get(name)
        if dev is None:
            return False, f"没有叫「{name}」的设备，我能控的是：{'、'.join(st.keys())}"

        if action == "on":
            dev["on"] = True
        elif action == "off":
            dev["on"] = False
        elif action == "toggle":
            dev["on"] = not bool(dev.get("on"))
        elif action in ("set", "brightness", "speed", "channel"):
            # set 动作：按 value 决定改哪个字段；显式字段名则只改那一个
            try:
                num = int(value)
            except (TypeError, ValueError):
                return False, f"「{action}」要给个数字，收到的是 {value!r}"
            if action == "brightness":
                dev["brightness"] = max(0, min(100, num))
            elif action == "speed":
                dev["speed"] = max(1, min(3, num))
            elif action == "channel":
                dev["channel"] = max(1, num)
            else:
                # 通用 set：按设备类型选一个合理字段
                if dev.get("kind") == "light":
                    dev["brightness"] = max(0, min(100, num))
                elif dev.get("kind") == "fan":
                    dev["speed"] = max(1, min(3, num))
                else:
                    dev["channel"] = max(1, num)
            if not dev.get("on"):
                dev["on"] = True
        else:
            return False, f"不认识的动作「{action}」，我只会 开/关/切换/设值"

        return True, describe(dev)


def _backend_call(ctx: Any, method: str, path: str, payload: dict | None) -> tuple[bool, Any]:
    """调老后端。任何异常都变成 (False, 人话)。"""
    base = str(C.cfg_get(ctx, "device.backend_url", "") or "").rstrip("/")
    if not base:
        return False, "配置里没有设备后端地址（device.backend_url），先把模拟开关打开吧"
    token = str(C.cfg_get(ctx, "device.token", "") or "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        import httpx

        url = f"{base}{path}"
        with httpx.Client(timeout=8.0, follow_redirects=True) as cli:
            r = cli.request(method, url, json=payload, headers=headers)
        if r.status_code >= 400:
            return False, f"设备后端回了 {r.status_code}"
        try:
            return True, r.json()
        except ValueError:
            return True, r.text[:200]
    except Exception as exc:  # noqa: BLE001
        return False, f"连不上设备后端（{type(exc).__name__}）"


def backend_list(ctx: Any) -> tuple[bool, Any]:
    return _backend_call(ctx, "GET", "/devices", None)


def backend_control(ctx: Any, name: str, action: str, value: Any) -> tuple[bool, Any]:
    payload = {"device": name, "action": action}
    if value is not None:
        payload["value"] = value
    return _backend_call(ctx, "POST", "/device/control", payload)


def backend_speak(ctx: Any, text: str) -> tuple[bool, Any]:
    return _backend_call(ctx, "POST", "/device/speak", {"text": text})


def push_speech(text: str) -> int:
    """模拟模式下把要说的句子塞进队列，返回队列长度。"""
    with _lock:
        _speech.append(text)
        if len(_speech) > _SPEECH_KEEP:
            del _speech[: len(_speech) - _SPEECH_KEEP]
        return len(_speech)


def last_speech(n: int = 5) -> list[str]:
    with _lock:
        return list(_speech[-n:])


def simulate_on(ctx: Any) -> bool:
    v = C.cfg_get(ctx, "device.simulate", True)
    return bool(v)
