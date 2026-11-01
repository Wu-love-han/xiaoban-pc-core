"""device.list：列出可控设备。

simulate=true 时列的是本进程内存里的真实状态（改过就能看到改的结果）；
simulate=false 时问老后端要列表，后端不通就给一句人话，不抛异常。
"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _devices as D


def run(args: dict, ctx: Any) -> dict:
    if D.simulate_on(ctx):
        devs = D.list_devices()
        if not devs:
            return C.ok("现在一个设备都没接上。", items=[], simulated=True)
        lines = [
            f"- {d['label']}（{d['name']}）：{'开' if d['on'] else '关'}"
            + (
                "，"
                + "，".join(f"{k}={v}" for k, v in (d.get("state") or {}).items())
                if d.get("state")
                else ""
            )
            for d in devs
        ]
        return C.ok(
            f"现在能控 {len(devs)} 个设备（模拟）：\n" + "\n".join(lines),
            items=devs,
            simulated=True,
        )

    ok, data = D.backend_list(ctx)
    if not ok:
        return C.fail(f"设备后端没响应：{data}", "DeviceBackendUnavailable")

    # 老后端返回形状未知，尽量从中抽出列表
    items: list = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("devices", "items", "data", "list"):
            v = data.get(key)
            if isinstance(v, list):
                items = v
                break

    if not items:
        return C.ok(f"设备后端回了内容但没有设备列表：{str(data)[:120]}", items=[], raw=data)

    return C.ok(f"现在能控 {len(items)} 个设备：{str(items)[:250]}", items=items, simulated=False)


TOOL = {
    "name": "device.list",
    "title": "看有哪些设备",
    "desc": "列出当前能控制的设备（灯、电视、风扇）以及它们现在是开还是关。",
    "danger": False,
    "params": {"type": "object", "properties": {}},
    "run": C.guard(run),
}
