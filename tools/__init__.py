"""tools 包：工具自动发现的入口。

契约 6.4：扫 `tools/*.py`，跳过 `_` 开头，收集模块级 `TOOL`。
真正的扫描/注册/执行逻辑在 `core.toolbase`，这里只做薄封装，
避免两处实现分叉。
"""

from __future__ import annotations

from core.toolbase import registry, load_all as _load_all

__all__ = ["registry", "load_all"]


def load_all(package: str = "tools") -> int:
    """加载全部工具，返回成功注册的数量。

    单个模块导入失败只记警告，不影响其它工具（契约 6.4）。
    """
    return _load_all(package)
