"""工具注册表：发现、校验、执行。

设计要点：
- **工具是数据，不是代码分支。** 每个工具模块暴露一个 TOOL 字典，这里负责收集。
- 新增工具 = 新建 tools/xxx.py，不改这个文件一行。
- 执行统一包 try/except，工具内部抛异常也变成 ok:False，绝不让大脑崩。
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("pccore.tools")

# 工具 output 进模型上下文，必须短
MAX_OUTPUT_CHARS = 3000  # 太小会让 AI 看不到结果，反复重试

# ------------------------------------------------------------------
# 工具名在「规范名」和「线上名」之间转换
#
# 规范名（我们内部和前端用）：pc.list_dir   —— 带命名空间，可读
# 线上名（发给模型的 function name）：pc_list_dir
#
# 为什么必须转：实测 DeepSeek/OpenAI 的函数名只接受 ^[a-zA-Z0-9_-]+$，
# 带点号会被直接 400 拒绝：
#   Invalid 'tools[0].function.name': string does not match pattern
# 这个坑不转的话，每个请求都会 400 然后降级，默认大脑等于用不上。
# ------------------------------------------------------------------
_NAME_UNSAFE = re.compile(r"[^a-zA-Z0-9_-]")


def to_wire(name: str) -> str:
    """规范名 → 线上名。pc.list_dir → pc_list_dir"""
    return _NAME_UNSAFE.sub("_", name or "")


@dataclass
class ToolContext:
    """执行一个工具时能拿到的东西。工具不许自己去读全局配置。"""

    session_id: str
    call_id: str
    workspace: Path
    config: dict = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    title: str
    desc: str
    danger: bool
    params: dict
    run: Callable[[dict, ToolContext], dict]

    def schema(self, wire_name: str | None = None) -> dict:
        """转成 OpenAI function-calling 的 tools[] 元素。

        name 用线上名（下划线），因为点号会被 provider 拒绝。
        """
        return {
            "type": "function",
            "function": {
                "name": wire_name or to_wire(self.name),
                "description": f"{self.title}：{self.desc}",
                "parameters": self.params or {"type": "object", "properties": {}},
            },
        }

    def public(self) -> dict:
        """给前端看的（不含 run）。"""
        return {
            "name": self.name,
            "title": self.title,
            "desc": self.desc,
            "danger": self.danger,
            "params": self.params,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        # 线上名 → 规范名。给 provider 收到 tool_call 时反查用。
        self._wire_to_canon: dict[str, str] = {}

    # ---------------------------------------------------------------- 注册
    def register(self, mod: Any) -> bool:
        spec = getattr(mod, "TOOL", None)
        if not isinstance(spec, dict):
            return False
        name = spec.get("name") or ""
        run = spec.get("run")
        if not name or not callable(run):
            logger.warning("工具模块 %s 的 TOOL 不完整，跳过", getattr(mod, "__name__", "?"))
            return False
        if name in self._tools:
            logger.warning("工具名重复：%s（%s），后注册的覆盖前一个", name, getattr(mod, "__name__", "?"))
        wire = to_wire(name)
        if wire in self._wire_to_canon and self._wire_to_canon[wire] != name:
            # 极端情况：pc.a_b 与 pc.a.b 会撞成同一个线上名。加后缀区分。
            suffix = 2
            while f"{wire}_{suffix}" in self._wire_to_canon:
                suffix += 1
            logger.warning("线上名冲突：%s 与 %s → %s", self._wire_to_canon[wire], name, f"{wire}_{suffix}")
            wire = f"{wire}_{suffix}"
        self._wire_to_canon[wire] = name
        self._tools[name] = ToolSpec(
            name=name,
            title=spec.get("title") or name,
            desc=spec.get("desc") or "",
            danger=bool(spec.get("danger")),
            params=spec.get("params") or {"type": "object", "properties": {}},
            run=run,
        )
        return True

    def load_package(self, package: str = "tools") -> int:
        """扫包下所有模块，收集 TOOL。单个模块导入失败不影响其它。"""
        n = 0
        try:
            pkg = importlib.import_module(package)
        except Exception as exc:  # noqa: BLE001
            logger.error("工具包 %s 导入失败：%s", package, exc)
            return 0

        pkg_path = getattr(pkg, "__path__", None)
        if not pkg_path:
            return 0

        for info in pkgutil.iter_modules(list(pkg_path)):
            if info.name.startswith("_"):
                continue
            mod_name = f"{package}.{info.name}"
            try:
                mod = importlib.import_module(mod_name)
                if self.register(mod):
                    n += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("工具模块 %s 加载失败：%s: %s", mod_name, type(exc).__name__, exc)
        logger.info("工具加载完成：%d 个", n)
        return n

    # ---------------------------------------------------------------- 查询
    def get(self, name: str) -> ToolSpec | None:
        """按规范名或线上名都能取到。"""
        spec = self._tools.get(name)
        if spec is not None:
            return spec
        canon = self._wire_to_canon.get(name)
        return self._tools.get(canon) if canon else None

    def to_canon(self, name: str) -> str:
        """线上名 → 规范名。已经是规范名就原样返回。"""
        if name in self._tools:
            return name
        return self._wire_to_canon.get(name, name)

    def wire_name(self, name: str) -> str:
        """规范名 → 本次注册实际用的线上名（处理过冲突后缀）。"""
        for wire, canon in self._wire_to_canon.items():
            if canon == name:
                return wire
        return to_wire(name)

    def unregister_prefix(self, prefix: str) -> int:
        """按规范名前缀撤销工具（卸载插件用）。返回撤销数量。"""
        removed = 0
        for name in [n for n in self._tools if n.startswith(prefix)]:
            del self._tools[name]
            for wire, canon in list(self._wire_to_canon.items()):
                if canon == name:
                    del self._wire_to_canon[wire]
            removed += 1
        return removed

    def all(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    def schemas(self) -> list[dict]:
        return [t.schema(self.wire_name(t.name)) for t in self.all()]

    def public_list(self) -> list[dict]:
        return [t.public() for t in self.all()]

    def names(self) -> list[str]:
        return [t.name for t in self.all()]

    def catalog_for_prompt(self) -> str:
        """给 system prompt 用的一行行能力摘要（不塞完整 JSON Schema，省 token）。"""
        lines = []
        for t in self.all():
            danger = "（需要我先问一句）" if t.danger else ""
            lines.append(f"- {t.title}：{t.desc}{danger}")
        return "\n".join(lines)

    # ---------------------------------------------------------------- 执行
    def execute(self, name: str, args: dict, ctx: ToolContext) -> dict:
        """同步执行，永不抛异常。返回 {ok, output, data?, error?}。"""
        t0 = time.perf_counter()
        spec = self.get(name)
        if spec is None:
            return {
                "ok": False,
                "output": f"没有这个工具：{name}",
                "error": "ToolNotFound",
                "ms": 0,
            }
        if not isinstance(args, dict):
            args = {}

        try:
            res = spec.run(args, ctx)
            if inspect.isawaitable(res):
                # 同步路径不支持协程工具；由 brain 的异步分支处理
                return {
                    "ok": False,
                    "output": f"{spec.title} 是异步工具，请走异步执行",
                    "error": "AsyncToolInSyncPath",
                    "ms": int((time.perf_counter() - t0) * 1000),
                }
        except Exception as exc:  # noqa: BLE001
            logger.exception("工具 %s 执行异常", name)
            return {
                "ok": False,
                "output": f"{spec.title}出错了：{type(exc).__name__}",
                "error": f"{type(exc).__name__}: {exc}",
                "ms": int((time.perf_counter() - t0) * 1000),
            }

        if not isinstance(res, dict):
            res = {"ok": True, "output": str(res)}

        ms = int((time.perf_counter() - t0) * 1000)
        out = str(res.get("output") or "")
        if len(out) > MAX_OUTPUT_CHARS:
            half = MAX_OUTPUT_CHARS // 2
            out = out[:half] + "\n…（中间省略）…\n" + out[-half:]
        res["output"] = out
        res.setdefault("ok", False)
        res["ms"] = ms
        return res

    async def aexecute(self, name: str, args: dict, ctx: ToolContext) -> dict:
        """异步执行。同步工具直接调，协程工具 await。"""
        spec = self.get(name)
        if spec is not None:
            try:
                probe = spec.run
                if inspect.iscoroutinefunction(probe):
                    t0 = time.perf_counter()
                    try:
                        res = await probe(args if isinstance(args, dict) else {}, ctx)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("异步工具 %s 执行异常", name)
                        return {
                            "ok": False,
                            "output": f"{spec.title}出错了：{type(exc).__name__}",
                            "error": f"{type(exc).__name__}: {exc}",
                            "ms": int((time.perf_counter() - t0) * 1000),
                        }
                    if not isinstance(res, dict):
                        res = {"ok": True, "output": str(res)}
                    out = str(res.get("output") or "")
                    if len(out) > MAX_OUTPUT_CHARS:
                        half = MAX_OUTPUT_CHARS // 2
                        out = out[:half] + "\n…（中间省略）…\n" + out[-half:]
                    res["output"] = out
                    res.setdefault("ok", False)
                    res["ms"] = int((time.perf_counter() - t0) * 1000)
                    return res
            except Exception:  # noqa: BLE001
                pass
        return self.execute(name, args, ctx)


# 全局单例（服务端启动时填充一次）
registry = ToolRegistry()


def load_all(package: str = "tools") -> int:
    return registry.load_package(package)
