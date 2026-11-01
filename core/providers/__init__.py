"""Provider 工厂：按配置选后端，并支持运行期切换。"""

from __future__ import annotations

import logging

from .. import config as cfg_mod
from .base import Provider, ProviderEvent, ToolCallAccumulator, parse_args
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

logger = logging.getLogger("pccore.provider")

_instances: dict[str, Provider] = {}


def get_provider(name: str | None = None) -> Provider:
    """按名字取 provider（带缓存）。名字空则读配置。"""
    cfg = cfg_mod.load()
    key = (name or (cfg.get("brain") or {}).get("provider") or "gateway").strip()

    if key in _instances:
        return _instances[key]

    providers = cfg.get("providers") or {}
    if key == "ollama":
        p = OllamaProvider(providers.get("ollama") or {})
    elif key in ("gateway", "openai", "cloud"):
        p = OpenAICompatProvider(providers.get("gateway") or {}, name=key)
    else:
        logger.warning("未知 provider %s，回落 gateway", key)
        p = OpenAICompatProvider(providers.get("gateway") or {}, name="gateway")
        key = "gateway"

    _instances[key] = p
    return p


def reset() -> None:
    """配置改了/测试用，丢掉缓存实例。"""
    _instances.clear()


__all__ = [
    "Provider",
    "ProviderEvent",
    "ToolCallAccumulator",
    "parse_args",
    "get_provider",
    "reset",
    "OllamaProvider",
    "OpenAICompatProvider",
]
