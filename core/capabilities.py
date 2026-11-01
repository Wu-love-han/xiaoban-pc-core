"""能力插槽框架（Capability Slots）。

小伴的数字生命能力（记忆/主动行为/直播/抖音/QQ/手机/开源模型适配……）
统一在这里注册。加一个新能力 = 新建一个模块，不需要改 main.py。

设计原则：
- 每个能力是一个模块，暴露 CAPABILITY 字典：
    CAPABILITY = {
        "id": "live",            # 唯一 id，^[a-z0-9_-]+$
        "name": "直播",
        "version": "0.1.0",
        "description": "AI 直播 + 虚拟形象",
        "enabled": False,         # 默认关（用户要时再开）
        "api": "live_api",        # 可选：挂载的 FastAPI 路由模块名（server/routes/ 下）
        "requires": [],           # 可选：依赖的 capability id
    }
- 能力有生命周期钩子（可选）：
    on_start(ctx) / on_stop(ctx)
- 后端启动时扫描 core/capabilities/*.py 或声明式清单注册。

现状（2026-11-01）：
- memory  记忆+情绪 —— enabled
- autopilot 主动行为 —— enabled
- live    直播/抖音 —— 预留（disabled，用户要时开）
- qq      QQ 接入 —— 预留
- models  开源模型适配 —— 预留（providers 已有 ollama/openai_compat）
"""

from __future__ import annotations

import importlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("pccore.capabilities")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# 预留清单：还没实现的能力也在这里登记，方便前端/用户看到"未来可插"
PRESET_CAPABILITIES: list[dict] = [
    {
        "id": "memory",
        "name": "记忆+情绪",
        "version": "0.1.0",
        "description": "分层记忆（短期/长期）、情绪状态、好感度",
        "enabled": True,
        "api": "memory_api",
        "requires": [],
    },
    {
        "id": "autopilot",
        "name": "主动行为",
        "version": "0.1.0",
        "description": "定时问候、提醒、记忆回想——自己找事做",
        "enabled": True,
        "api": "autopilot_api",
        "requires": [],
    },
    {
        "id": "live",
        "name": "直播/抖音",
        "version": "预留",
        "description": "AI 直播 + 虚拟形象 + 弹幕进脑子；抖音/快手等平台接入",
        "enabled": False,
        "api": "live_api",
        "requires": [],
        "planned": True,
    },
    {
        "id": "qq",
        "name": "QQ 接入",
        "version": "预留",
        "description": "QQ 机器人（NapCat/Lagrange）接入，小伴住进 QQ 陪你玩",
        "enabled": False,
        "api": None,
        "requires": [],
        "planned": True,
    },
    {
        "id": "models",
        "name": "开源模型适配",
        "version": "预留",
        "description": "拉取开源模型（Ollama/GGUF 等）并做适配层，本地可跑",
        "enabled": False,
        "api": None,
        "requires": [],
        "planned": True,
    },
]


@dataclass
class Capability:
    id: str
    name: str
    version: str = "0.0.0"
    description: str = ""
    enabled: bool = False
    api: str | None = None
    requires: list[str] = field(default_factory=list)
    planned: bool = False


_registry: dict[str, Capability] = {}


def _load_presets() -> None:
    for item in PRESET_CAPABILITIES:
        cap = Capability(
            id=item["id"],
            name=item.get("name", item["id"]),
            version=item.get("version", "0.0.0"),
            description=item.get("description", ""),
            enabled=bool(item.get("enabled")),
            api=item.get("api"),
            requires=list(item.get("requires") or []),
            planned=bool(item.get("planned")),
        )
        _registry[cap.id] = cap


def list_capabilities() -> list[dict]:
    """列出所有能力（含预留）。"""
    if not _registry:
        _load_presets()
    return [
        {
            "id": c.id,
            "name": c.name,
            "version": c.version,
            "description": c.description,
            "enabled": c.enabled,
            "api": c.api,
            "requires": c.requires,
            "planned": c.planned,
        }
        for c in sorted(_registry.values(), key=lambda x: x.id)
    ]


def get_capability(cap_id: str) -> Capability | None:
    if not _registry:
        _load_presets()
    return _registry.get(cap_id)


def is_planned(cap_id: str) -> bool:
    cap = get_capability(cap_id)
    return bool(cap and cap.planned)


def enabled_ids() -> list[str]:
    return [c.id for c in _registry.values() if c.enabled]
