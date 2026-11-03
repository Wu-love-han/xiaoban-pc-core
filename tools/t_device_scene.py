"""device.scene：一键场景（我要睡了 / 出门 / 回家 / 工作）。

小伴的需求：「家里设备的控制希望能和场景联动，比如『我要睡了』一键关灯关电视」
"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _devices as D

# 场景定义：设备 → 动作
SCENES: dict[str, dict] = {
    "sleep": {
        "title": "睡觉",
        "aliases": ["睡了", "睡觉", "晚安", "要睡了", "去睡"],
        "actions": [("灯", "off", None), ("电视", "off", None), ("风扇", "off", None)],
        "say": "灯、电视、风扇都关了。晚安，早点睡。",
    },
    "leave": {
        "title": "出门",
        "aliases": ["出门", "走了", "我出去", "离开"],
        "actions": [("灯", "off", None), ("电视", "off", None), ("风扇", "off", None)],
        "say": "该关的都关了，路上小心。",
    },
    "home": {
        "title": "回家",
        "aliases": ["回家", "我回来了", "到家"],
        "actions": [("灯", "on", None), ("风扇", "on", None)],
        "say": "灯给你开好了，风扇也转了。",
    },
    "work": {
        "title": "工作",
        "aliases": ["工作", "干活", "开始工作", "学习"],
        "actions": [("灯", "set", 80), ("电视", "off", None), ("风扇", "on", None)],
        "say": "灯调到 80，电视关了，风扇开着。专心干吧。",
    },
}


def _match_scene(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in SCENES:
        return s
    for key, conf in SCENES.items():
        for a in conf["aliases"]:
            if a in s or s in a:
                return key
    return ""


def run(args: dict, ctx: Any) -> dict:
    # 列场景
    if bool(args.get("list")) or str(args.get("scene") or "").lower() in ("list", "all"):
        lines = [f"- {k}（{v['title']}）：{v['say']}" for k, v in SCENES.items()]
        return C.ok("现在有这些场景：\n" + "\n".join(lines), scenes=list(SCENES))

    raw = str(args.get("scene") or args.get("name") or args.get("text") or "").strip()
    key = _match_scene(raw)
    if not key:
        names = "、".join(f"{v['title']}（{k}）" for k, v in SCENES.items())
        return C.fail(f"认不出这个场景「{raw}」。现在有：{names}", "UnknownScene")

    conf = SCENES[key]
    done, failed = [], []
    sim = D.simulate_on(ctx)
    for name, action, value in conf["actions"]:
        try:
            norm = D.normalize_name(name) or name
            if sim:
                ok, msg = D.apply_sim(norm, action, value)
            else:
                ok, msg = D.backend_control(ctx, norm, action, value)
            if ok:
                done.append(f"{name} {action}")
            else:
                failed.append(f"{name}: {msg}")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}: {exc}")

    msg = conf["say"]
    if failed:
        msg += f"（有 {len(failed)} 个没成：{'；'.join(failed[:3])}）"
    return C.ok(msg, scene=key, done=done, failed=failed, simulated=sim)


TOOL = {
    "name": "device.scene",
    "title": "一键场景",
    "desc": "一键执行场景联动：睡觉（关灯关电视关风扇）、出门（全关）、回家（开灯开风扇）、工作（灯调80、关电视、开风扇）。用户说「我要睡了」这类话时用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "scene": {"type": "string", "description": "场景：sleep / leave / home / work，或者用户原话"},
            "list": {"type": "boolean", "description": "true 时列出所有场景"},
        },
    },
    "run": C.guard(run),
}
