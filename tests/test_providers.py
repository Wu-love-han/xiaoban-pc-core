"""Provider 层测试：重点是流式 tool_calls 增量合并（实测最易错的地方）。"""

from __future__ import annotations

import json

from core.providers.base import ProviderEvent, ToolCallAccumulator, parse_args


def test_accumulator_merges_single_char_chunks():
    """实测网关把 arguments 切成单字符片段，必须拼回完整 JSON。"""
    acc = ToolCallAccumulator()
    acc.feed([{"index": 0, "id": "call_1", "function": {"name": "pc.list_dir", "arguments": ""}}])
    for ch in '{"path": "E:\\\\WH"}':
        acc.feed([{"index": 0, "function": {"arguments": ch}}])

    out = acc.results()
    assert len(out) == 1
    ev = out[0]
    assert ev.kind == "tool_call"
    assert ev.call_id == "call_1"
    assert ev.name == "pc.list_dir"
    args, err = parse_args(ev.arguments)
    assert err == ""
    assert args == {"path": "E:\\WH"}


def test_accumulator_keeps_two_calls_separate():
    acc = ToolCallAccumulator()
    acc.feed([
        {"index": 0, "id": "a", "function": {"name": "pc.list_dir", "arguments": "{\"path\""}},
        {"index": 1, "id": "b", "function": {"name": "sys.info", "arguments": "{"}},
    ])
    acc.feed([
        {"index": 0, "function": {"arguments": ": \"E:\\\\WH\"}"}},
        {"index": 1, "function": {"arguments": "}"}},
    ])
    out = acc.results()
    assert [e.name for e in out] == ["pc.list_dir", "sys.info"]
    assert parse_args(out[0].arguments)[0] == {"path": "E:\\WH"}
    assert parse_args(out[1].arguments)[0] == {}


def test_accumulator_skips_nameless():
    acc = ToolCallAccumulator()
    acc.feed([{"index": 0, "function": {"arguments": "{}"}}])
    assert acc.results() == []
    assert not acc


def test_accumulator_dict_arguments():
    acc = ToolCallAccumulator()
    acc.feed([{"index": 0, "id": "x", "function": {"name": "t", "arguments": {"a": 1}}}])
    out = acc.results()
    assert json.loads(out[0].arguments) == {"a": 1}


def test_parse_args_variants():
    assert parse_args('{"a":1}') == ({"a": 1}, "")
    assert parse_args("") == ({}, "")
    args, err = parse_args("{bad json")
    assert args == {} and err
    args, err = parse_args("[1,2]")
    assert args == {} and "对象" in err


def test_provider_event_defaults():
    ev = ProviderEvent(kind="content", text="hi")
    assert ev.call_id == "" and ev.usage == {}


# ---------------------------------------------------------------- 真实网关连通性
# 这条会真的打本机网关；没开就 skip，不算失败。

def test_gateway_reachable():
    import httpx
    import pytest

    try:
        r = httpx.get("http://127.0.0.1:3425/v1/models", timeout=5.0)
    except Exception:  # noqa: BLE001
        pytest.skip("本机网关未启动")
    assert r.status_code == 200
    assert isinstance(r.json().get("data"), list)
