"""工具层测试：注册表行为 + 工具契约（不依赖具体工具实现细节）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.toolbase import MAX_OUTPUT_CHARS, ToolContext, ToolRegistry


class _Mod:
    """伪造一个工具模块。"""

    def __init__(self, spec):
        self.TOOL = spec
        self.__name__ = "fake_mod"


def _ctx(tmp_path) -> ToolContext:
    return ToolContext(session_id="s_x", call_id="c_x", workspace=tmp_path, config={})


def test_register_and_schema():
    reg = ToolRegistry()

    def run(args, ctx):
        return {"ok": True, "output": "hi"}

    ok = reg.register(_Mod({
        "name": "t.demo", "title": "演示", "desc": "说明",
        "danger": False,
        "params": {"type": "object", "properties": {"x": {"type": "string"}}},
        "run": run,
    }))
    assert ok
    assert reg.names() == ["t.demo"]
    schema = reg.schemas()[0]
    assert schema["type"] == "function"
    # schema 用线上名（点号转下划线），因为 provider 不接受点号
    assert schema["function"]["name"] == "t_demo"
    assert "演示" in schema["function"]["description"]


def test_register_rejects_incomplete():
    reg = ToolRegistry()
    assert reg.register(_Mod({"name": "x"})) is False          # 没 run
    assert reg.register(_Mod({"run": lambda a, c: {}})) is False  # 没 name
    assert reg.register(object()) is False


def test_execute_success(tmp_path):
    reg = ToolRegistry()
    reg.register(_Mod({
        "name": "t.ok", "title": "T", "desc": "", "danger": False,
        "params": {}, "run": lambda a, c: {"ok": True, "output": "done"},
    }))
    res = reg.execute("t.ok", {}, _ctx(tmp_path))
    assert res["ok"] is True
    assert res["output"] == "done"
    assert "ms" in res


def test_execute_unknown_tool(tmp_path):
    reg = ToolRegistry()
    res = reg.execute("nope", {}, _ctx(tmp_path))
    assert res["ok"] is False
    assert "没有这个工具" in res["output"]


def test_execute_swallows_exception(tmp_path):
    """工具内部炸了，不能让大脑崩。"""
    reg = ToolRegistry()

    def boom(args, ctx):
        raise ValueError("炸了")

    reg.register(_Mod({
        "name": "t.boom", "title": "炸", "desc": "", "danger": False,
        "params": {}, "run": boom,
    }))
    res = reg.execute("t.boom", {}, _ctx(tmp_path))
    assert res["ok"] is False
    assert "ValueError" in res["error"]
    assert "炸" in res["output"]


def test_execute_truncates_output(tmp_path):
    reg = ToolRegistry()
    long = "啊" * (MAX_OUTPUT_CHARS + 500)
    reg.register(_Mod({
        "name": "t.long", "title": "长", "desc": "", "danger": False,
        "params": {}, "run": lambda a, c: {"ok": True, "output": long},
    }))
    res = reg.execute("t.long", {}, _ctx(tmp_path))
    assert len(res["output"]) <= MAX_OUTPUT_CHARS + 10
    assert res["output"].endswith("（已截断）")


def test_catalog_for_prompt_marks_danger():
    reg = ToolRegistry()
    for name, danger in (("t.safe", False), ("t.danger", True)):
        reg.register(_Mod({
            "name": name, "title": name, "desc": "d", "danger": danger,
            "params": {}, "run": lambda a, c: {"ok": True, "output": ""},
        }))
    cat = reg.catalog_for_prompt()
    assert "t.danger" in cat
    assert "需要我先问一句" in cat


@pytest.mark.asyncio
async def test_aexecute_sync_tool(tmp_path):
    reg = ToolRegistry()
    reg.register(_Mod({
        "name": "t.s", "title": "S", "desc": "", "danger": False,
        "params": {}, "run": lambda a, c: {"ok": True, "output": "sync"},
    }))
    res = await reg.aexecute("t.s", {}, _ctx(tmp_path))
    assert res["ok"] and res["output"] == "sync"


@pytest.mark.asyncio
async def test_aexecute_async_tool(tmp_path):
    reg = ToolRegistry()

    async def arun(args, ctx):
        return {"ok": True, "output": "async"}

    reg.register(_Mod({
        "name": "t.a", "title": "A", "desc": "", "danger": False,
        "params": {}, "run": arun,
    }))
    res = await reg.aexecute("t.a", {}, _ctx(tmp_path))
    assert res["ok"] and res["output"] == "async"


# ---------------------------------------------------------------- 真实工具包
def test_real_tool_package_loads():
    """tools/ 包必须能加载出契约规定的 18 个工具。"""
    from core.toolbase import registry

    registry._tools.clear()
    n = registry.load_package("tools")
    names = set(registry.names())
    expected = {
        "sys.info", "sys.time", "pc.open_app", "pc.list_dir", "pc.read_file",
        "pc.write_file", "pc.append_file", "pc.mkdir", "pc.delete",
        "pc.search_files", "pc.shell", "net.web_search", "net.fetch",
        "mem.remember", "mem.recall", "device.list", "device.control", "device.speak",
    }
    missing = expected - names
    assert not missing, f"缺工具：{missing}（实际加载 {n} 个）"


def test_danger_flags_exact():
    """danger 标记必须与契约一致，多一个都不行。"""
    from core.toolbase import registry

    if not registry.names():
        registry.load_package("tools")
    danger = {t.name for t in registry.all() if t.danger}
    assert danger == {"pc.write_file", "pc.delete", "pc.shell"}


# ---------------------------------------------------------------- 工具名转换
def test_to_wire_name():
    """点号必须转下划线，否则 provider 400。"""
    from core.toolbase import to_wire

    assert to_wire("pc.list_dir") == "pc_list_dir"
    assert to_wire("sys.info") == "sys_info"
    assert to_wire("device.control") == "device_control"
    # 本来就合法的原样返回
    assert to_wire("already_ok-1") == "already_ok-1"


def test_schema_uses_wire_name():
    """发出去的 schema 名字里绝不能有点号。"""
    import re

    from core.toolbase import registry

    if not registry.names():
        registry.load_package("tools")
    for schema in registry.schemas():
        name = schema["function"]["name"]
        assert re.fullmatch(r"[a-zA-Z0-9_-]+", name), f"线上名不合法：{name}"


def test_wire_roundtrip():
    """规范名 → 线上名 → 规范名，必须回到原样。"""
    from core.toolbase import registry

    if not registry.names():
        registry.load_package("tools")
    for name in registry.names():
        wire = registry.wire_name(name)
        assert registry.to_canon(wire) == name
        # 规范名本身也能取到
        assert registry.get(name) is not None
        # 线上名也能取到
        assert registry.get(wire) is not None


def test_wire_name_collision_gets_suffix():
    """pc.a_b 与 pc.a.b 会撞同一个线上名，必须自动加后缀。"""
    from core.toolbase import ToolRegistry

    reg = ToolRegistry()

    def mk(name):
        return type("M", (), {
            "TOOL": {"name": name, "title": name, "desc": "", "danger": False,
                     "params": {}, "run": lambda a, c: {"ok": True, "output": ""}},
            "__name__": "fake",
        })

    reg.register(mk("pc.a_b"))
    reg.register(mk("pc.a.b"))
    wires = {n: reg.wire_name(n) for n in reg.names()}
    assert len(set(wires.values())) == 2, f"线上名撞了：{wires}"
    assert reg.to_canon(wires["pc.a.b"]) == "pc.a.b"
    assert reg.to_canon(wires["pc.a_b"]) == "pc.a_b"
