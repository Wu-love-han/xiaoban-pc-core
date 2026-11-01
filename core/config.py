"""配置读写。

设计：config.json 是唯一真源；文件缺失或坏掉时用 DEFAULT_CONFIG 兜底并重建。
嵌套字典做浅层合并（两层），这样新增配置项不会因为旧文件缺键而 KeyError。
"""

from __future__ import annotations

import copy
import json
import threading
from typing import Any

from .paths import CONFIG_FILE, DEFAULT_CONFIG, ensure_dirs

_lock = threading.RLock()
_cache: dict | None = None
_cache_mtime: float = 0.0


def _deep_merge(base: dict, over: dict) -> dict:
    """两层合并：base 提供默认，over 覆盖。值不是 dict 就直接覆盖。"""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load(force: bool = False) -> dict:
    """读配置（带 mtime 缓存，手改文件后自动生效）。"""
    global _cache, _cache_mtime
    with _lock:
        ensure_dirs()
        try:
            mtime = CONFIG_FILE.stat().st_mtime
        except OSError:
            mtime = 0.0

        if _cache is not None and not force and mtime == _cache_mtime:
            return _cache

        raw: dict = {}
        if CONFIG_FILE.exists():
            try:
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8") or "{}")
            except (json.JSONDecodeError, OSError):
                raw = {}
        merged = _deep_merge(DEFAULT_CONFIG, raw)
        _cache = merged
        _cache_mtime = mtime

        # 文件不存在/为空 → 写一份出来，方便手改
        if not CONFIG_FILE.exists() or not raw:
            save(merged)
        return merged


def save(cfg: dict) -> None:
    """写回配置文件（UTF-8 无 BOM，缩进 2）。"""
    global _cache, _cache_mtime
    with _lock:
        ensure_dirs()
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        try:
            _cache_mtime = CONFIG_FILE.stat().st_mtime
        except OSError:
            _cache_mtime = 0.0
        _cache = cfg


def patch(section: str, values: dict) -> dict:
    """改某个 section 下的几个键并落盘。"""
    with _lock:
        cfg = load(force=True)
        cfg.setdefault(section, {})
        cfg[section].update(values)
        save(cfg)
        return cfg


def get(path: str, default: Any = None) -> Any:
    """点号取值：get("brain.model")。"""
    cur: Any = load()
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def redacted() -> dict:
    """给前端看的配置：token/key 一律脱敏。"""
    cfg = copy.deepcopy(load())
    srv = cfg.get("server") or {}
    if srv.get("auth_token"):
        srv["auth_token"] = "***"
    for p in (cfg.get("providers") or {}).values():
        if isinstance(p, dict) and p.get("api_key"):
            p["api_key"] = "***"
    dev = cfg.get("device") or {}
    if dev.get("token"):
        dev["token"] = "***"
    return cfg
