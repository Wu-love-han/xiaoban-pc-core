"""device.control：控设备（灯 / 电视 / 风扇）。

参数尽量宽容，因为模型说法五花八门：
    {"device":"灯","action":"关"}
    {"device":"light","action":"off"}
    {"device":"light","action":"set","value":60}
    {"device":"light","action":"brightness","value":60}
    {"name":"客厅灯","on":false}

模拟模式下状态真的写进进程内存，同一个进程里再 device.list 能看到变化——
不是每次返回一个假的固定值。
"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _devices as D


def _extract(args: dict) -> tuple[str, str, Any]:
    """从各种参数形状里抽出 (设备名, 归一动作, 值)。"""
    name = args.get("device") or args.get("name") or args.get("target") or ""
    raw_action = args.get("action") or args.get("cmd") or args.get("command") or ""

    value: Any = args.get("value")
    if value is None:
        value = args.get("brightness")
        if value is not None:
            raw_action = raw_action or "brightness"
    if value is None:
        value = args.get("speed")
        if value is not None:
            raw_action = raw_action or "speed"
    if value is None:
        value = args.get("channel")
        if value is not None:
            raw_action = raw_action or "channel"

    # 也接受 {"on": true} 这种布尔写法
    if not raw_action:
        for k in ("on", "power", "enabled"):
            if k in args and args[k] is not None:
                raw_action = "on" if args[k] else "off"
                break

    return D.normalize_name(name), D.normalize_action(raw_action), value


def run(args: dict, ctx: Any) -> dict:
    name, action, value = _extract(args)

    if not name:
        return C.fail("要控哪个设备呢？我能控的是：灯、电视、风扇。", "MissingArg: device")
    if not action:
        return C.fail(f"要对「{name}」做什么？开、关、还是设个值？", "MissingArg: action")

    if D.simulate_on(ctx):
        ok, msg = D.apply_sim(name, action, value)
        if not ok:
            return C.fail(msg, "SimulateFailed")
        return C.ok(f"{msg}（模拟）", device=name, action=action, simulated=True)

    ok, data = D.backend_control(ctx, name, action, value)
    if not ok:
        return C.fail(f"{name} 没控成：{data}", "DeviceBackendUnavailable")
    return C.ok(f"{name} 的 {action} 指令已经发给设备后端了。", device=name, action=action, raw=data)


TOOL = {
    "name": "device.control",
    "title": "控设备",
    "desc": "控制灯、电视、风扇：开、关、切换，或者设亮度/档位/频道。比如「关灯」用 device=灯 action=off，「灯调到 30」用 action=set value=30。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "device": {
                "type": "string",
                "description": "设备：灯 / 电视 / 风扇（也接受 light/tv/fan）",
            },
            "action": {
                "type": "string",
                "description": "动作：on/off/toggle（开/关/切换），或 set 配合 value 设值",
            },
            "value": {
                "type": "integer",
                "description": "可选数值：灯的亮度 0-100、风扇档位 1-3、电视频道",
            },
        },
        "required": ["device", "action"],
    },
    "run": C.guard(run),
}
