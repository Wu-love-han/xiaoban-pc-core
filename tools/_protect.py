"""系统目录保护：防止 AI 误删/误改程序文件。

背景（2026-11-04 血的教训）：
  为了给 QQ 装 NapCat，我把 QQ 官方的
  resources/app/package.json 覆盖后删掉，导致 QQ 报"文件已损坏"，
  用户只能重装。

  根本原因：AI 分不清「程序自带的文件」和「自己创建的临时文件」。

  这个模块在写/删之前拦一道，要求：
  1. Program Files 下的文件 → 必须显式传 allow_system=true
  2. 任何删除 → 先备份
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

# 系统程序目录（这些地方的文件一律当"程序自带的"）
SYSTEM_DIRS = (
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\windows",
    "c:\\programdata",
)


def is_system_path(p: str | Path) -> bool:
    """这个路径是不是在系统程序目录下。"""
    try:
        low = str(Path(p).resolve()).lower()
    except Exception:  # noqa: BLE001
        low = str(p).lower()
    return any(low.startswith(d) for d in SYSTEM_DIRS)


def looks_like_program_file(p: str | Path) -> bool:
    """看起来像程序自带的文件吗（安装日期 / 在系统目录）。"""
    path = Path(p)
    if is_system_path(path):
        return True
    if not path.exists():
        return False
    try:
        # 文件比当前进程启动还早很多 → 可能是安装时就有的
        age_days = (time.time() - path.stat().st_mtime) / 86400
        return age_days > 30
    except Exception:  # noqa: BLE001
        return False


def backup(p: str | Path, backup_root: str | Path | None = None) -> Path | None:
    """备份一个文件，返回备份路径。目录不备份（太大）。"""
    path = Path(p)
    if not path.exists() or path.is_dir():
        return None
    root = Path(backup_root or r"E:\WH\backups")
    try:
        root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        # 保留原路径信息，避免同名冲突
        safe = str(path).replace(":", "").replace("\\", "_").replace("/", "_")
        dst = root / f"{safe}.{stamp}.bak"
        shutil.copy2(path, dst)
        return dst
    except Exception:  # noqa: BLE001
        return None


def guard_write(p: str | Path, allow_system: bool) -> tuple[bool, str]:
    """写文件前的检查。返回 (能不能写, 原因)。"""
    if is_system_path(p) and not allow_system:
        return False, (
            f"「{p}」在系统程序目录里（Program Files / Windows）。\n"
            "这里面的文件基本都是程序自带的，改了可能让程序起不来"
            "（2026-11-04 就因为删了 QQ 的 package.json 导致 QQ 重装）。\n\n"
            "真要改，请：\n"
            "1. 先告诉我这是干什么用的\n"
            "2. 传 allow_system=true 明确表示你确认了\n"
            "3. 我会先自动备份到 E:\\WH\\backups\\"
        )
    return True, ""


def guard_delete(p: str | Path, allow_system: bool) -> tuple[bool, str]:
    """删文件前的检查。"""
    if is_system_path(p) and not allow_system:
        return False, (
            f"「{p}」在系统程序目录里，不能删。\n"
            "删程序文件会让程序坏掉，用户只能重装。\n"
            "如果确实要删，传 allow_system=true，并且我会先备份。"
        )
    return True, ""
