"""工具层共用的小零件：截断、错误包装、路径解析、配置取值。

下划线开头，registry 扫描时会被跳过，不会被当成工具加载。

为什么要有这个文件：18 个工具都要做同样三件事——把 output 压到 400 字、
把任何异常变成 ok:False、把相对路径落到 workspace。抄 18 遍不如放一处。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

# 契约 6.1：output 进模型上下文，必须 ≤400 字
MAX_OUT = 400
_CLIP_SUFFIX = "…（已截断）"


# ---------------------------------------------------------------- 输出
def clip(text: Any, limit: int = MAX_OUT) -> str:
    """压到 limit 字以内。换行统一成 \\n，避免 SSE/日志里出现裸 \\r。"""
    s = "" if text is None else str(text)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if len(s) <= limit:
        return s
    keep = max(0, limit - len(_CLIP_SUFFIX))
    return s[:keep] + _CLIP_SUFFIX


def ok(output: Any, **data: Any) -> dict:
    """成功返回。data 里可以塞任意结构，给程序用；output 给人/模型看。"""
    res: dict = {"ok": True, "output": clip(output)}
    if data:
        res["data"] = data
    return res


def fail(output: Any, error: str = "") -> dict:
    """失败返回。output 必须是「一句人话」，error 给排查用。"""
    return {"ok": False, "output": clip(output), "error": error or "ToolError"}


def guard(fn: Callable) -> Callable:
    """把工具函数包一层：任何异常都变成 ok:False，绝不让大脑崩。"""

    def wrapper(args: Any, ctx: Any) -> dict:
        try:
            return fn(args if isinstance(args, dict) else {}, ctx)
        except MissingPath:
            return fail("这个动作需要一个路径，但你没给我。", "MissingArg: path")
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            return fail(
                f"这个动作没做成（{name}），我换个办法再试。",
                f"{name}: {exc}",
            )

    wrapper.__name__ = getattr(fn, "__name__", "run")
    wrapper.__doc__ = getattr(fn, "__doc__", None)
    return wrapper


# ---------------------------------------------------------------- 配置
def cfg_of(ctx: Any) -> dict:
    """拿配置。优先用 ctx.config（brain 传进来的），没有就现读一份。"""
    c = getattr(ctx, "config", None)
    if isinstance(c, dict) and c:
        return c
    try:
        from core import config as cfg_mod

        return cfg_mod.load()
    except Exception:  # noqa: BLE001
        return {}


def cfg_get(ctx: Any, dotted: str, default: Any = None) -> Any:
    """点号取值：cfg_get(ctx, "tools.shell_whitelist", [])。"""
    cur: Any = cfg_of(ctx)
    for part in str(dotted).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


# ---------------------------------------------------------------- 路径
def workspace(ctx: Any) -> Path:
    w = getattr(ctx, "workspace", None)
    if isinstance(w, Path):
        return w
    try:
        from core.paths import WORKSPACE

        return Path(WORKSPACE)
    except Exception:  # noqa: BLE001
        return Path.cwd()


class MissingPath(ValueError):
    """参数里没给路径。单独一个类型，工具可以据此给出「一句人话」。"""


def resolve_path(raw: Any, ctx: Any, default_to_workspace: bool = False) -> Path:
    """把模型给的路径字符串变成 Path。

    - 空 → workspace（仅当 default_to_workspace）
    - 相对路径 → 落到 workspace 下（契约 6.2：写文件默认落 workspace）
    - 展开 ~ 和环境变量
    """
    s = "" if raw is None else str(raw).strip().strip('"').strip("'")
    if not s:
        if default_to_workspace:
            return workspace(ctx)
        raise MissingPath("没给路径")
    s = os.path.expandvars(os.path.expanduser(s))
    p = Path(s)
    if not p.is_absolute():
        p = workspace(ctx) / p
    return p


def human_size(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.0f}{unit}" if unit == "B" else f"{f:.1f}{unit}"
        f /= 1024
    return f"{f:.1f}TB"


# ---------------------------------------------------------------- 数据库
_db_ready = False


def ensure_db() -> None:
    """懒初始化数据库表（服务端启动时会 init，脚本/单测里不一定）。"""
    global _db_ready
    if _db_ready:
        return
    from core import db

    db.init()
    _db_ready = True
