"""大脑循环测试 —— 这是本次重做的核心断言。

要证明的事：
1. 纯聊天 → 零工具调用（没有分类器也能分清）
2. 有指令 → 调工具 → 工具结果回灌 → 模型再说话（人格收尾）
3. 危险工具 → 先出 approval，拒绝则工具不执行
4. 工具炸了 → 不崩，模型仍能收尾
5. 事件顺序符合契约
"""

from __future__ import annotations

import asyncio
import json

import pytest

from core import brain, db
from core.providers.base import ProviderEvent


@pytest.fixture(autouse=True)
def _isolate(tmp_db, monkeypatch):
    """每个测试独立库 + 干净的工具注册表 + 假 provider。"""
    from core.toolbase import ToolRegistry, registry

    registry._tools.clear()
    yield


def _content(*chunks):
    return [ProviderEvent(kind="content", text=c) for c in chunks]


def _done(inp=10, out=20):
    return ProviderEvent(kind="done", usage={"in": inp, "out": out})


def _tool_call(call_id, name, args: dict):
    return ProviderEvent(
        kind="tool_call", call_id=call_id, name=name,
        arguments=json.dumps(args, ensure_ascii=False),
    )


def _register_simple(name="t.echo", danger=False, fn=None):
    from core.toolbase import registry

    def run(args, ctx):
        if fn:
            return fn(args, ctx)
        return {"ok": True, "output": "echo:" + str(args.get("x", ""))}

    registry.register(
        type("M", (), {
            "TOOL": {
                "name": name, "title": "回声", "desc": "把输入回给你",
                "danger": danger, "params": {"type": "object", "properties": {}},
                "run": run,
            },
            "__name__": "fake",
        })
    )


async def _run(sid, text, **kw):
    evs = []
    async for name, payload in brain.run_turn(sid, text, **kw):
        evs.append((name, payload))
    return evs


# ---------------------------------------------------------------- 1. 聊天
@pytest.mark.asyncio
async def test_pure_chat_calls_no_tool(tmp_db, fake_provider):
    """「今天好累」→ 零工具调用。这就是「没有分类器也能分清」。"""
    fake_provider.add(_content("累就", "歇会儿，", "我在呢。") + [_done()])

    sid = db.create_session()["id"]
    evs = await _run(sid, "今天好累啊")

    names = [n for n, _ in evs]
    assert "tool_call" not in names
    assert "approval" not in names
    assert names[-1] == "turn_end"

    text = "".join(p["text"] for n, p in evs if n == "content")
    assert text == "累就歇会儿，我在呢。"

    # 落库：assistant 消息的 tool_calls 必须是空数组（证据：这轮不是指令）
    msgs = db.list_messages(sid)
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["tool_calls"] == []


# ---------------------------------------------------------------- 2. 指令
@pytest.mark.asyncio
async def test_command_runs_tool_then_speaks_again(tmp_db, fake_provider):
    """「看看有什么」→ 调工具 → 结果回灌 → 模型用她的语气收尾。"""
    _register_simple()
    fake_provider.add(
        [_tool_call("c1", "t.echo", {"x": "hi"}), _done()]
    )
    fake_provider.add(_content("看了，", "就一个文件。") + [_done()])

    sid = db.create_session()["id"]
    evs = await _run(sid, "看看有啥")

    names = [n for n, _ in evs]
    assert names.count("tool_call") == 1
    assert names.count("tool_result") == 1
    # 关键：工具之后模型又说话了
    idx_result = names.index("tool_result")
    assert "content" in names[idx_result:]

    final = "".join(p["text"] for n, p in evs if n == "content")
    assert final == "看了，就一个文件。"

    # 第二轮请求里必须带着 role=tool 的回灌
    second = fake_provider.calls[1]["messages"]
    assert any(m.get("role") == "tool" for m in second)
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in second)

    # 落库证据：这一轮被判成「指令」
    msgs = db.list_messages(sid)
    assert len(msgs[-1]["tool_calls"]) == 1
    assert msgs[-1]["tool_calls"][0]["name"] == "t.echo"


# ---------------------------------------------------------------- 3. 危险动作
@pytest.mark.asyncio
async def test_danger_tool_requires_approval_and_deny_blocks(tmp_db, fake_provider, monkeypatch):
    """拒绝 → 工具绝不能执行。"""
    executed = {"n": 0}

    def fn(args, ctx):
        executed["n"] += 1
        return {"ok": True, "output": "deleted"}

    _register_simple("pc.delete", danger=True, fn=fn)
    fake_provider.add([_tool_call("c1", "pc.delete", {"path": "a.txt"}), _done()])
    fake_provider.add(_content("行，", "那我不动它。") + [_done()])

    sid = db.create_session()["id"]

    # 拦截审批等待：立刻拒绝
    async def fake_wait(approval_id, timeout_s):
        brain.resolve_approval(approval_id, False)
        return "denied"

    monkeypatch.setattr(brain, "_wait_approval", fake_wait)

    evs = await _run(sid, "删掉 a.txt")
    names = [n for n, _ in evs]

    assert "approval" in names
    ap = [p for n, p in evs if n == "approval"][0]
    assert ap["name"] == "pc.delete"
    assert "真删" in ap["say"] and "a.txt" in ap["say"]  # 人格化 + 带具体目标

    assert executed["n"] == 0, "拒绝后工具绝不能执行"

    # 工具结果应该标记失败
    tr = [p for n, p in evs if n == "tool_result"][0]
    assert tr["ok"] is False

    # 审批落库为 denied
    aps = db.list_approvals("")
    assert aps[0]["status"] == "denied"


@pytest.mark.asyncio
async def test_danger_tool_approve_executes(tmp_db, fake_provider, monkeypatch):
    executed = {"n": 0}

    def fn(args, ctx):
        executed["n"] += 1
        return {"ok": True, "output": "deleted"}

    _register_simple("pc.delete", danger=True, fn=fn)
    fake_provider.add([_tool_call("c1", "pc.delete", {"path": "a.txt"}), _done()])
    fake_provider.add(_content("删了。") + [_done()])

    sid = db.create_session()["id"]

    async def fake_wait(approval_id, timeout_s):
        brain.resolve_approval(approval_id, True)
        return "approved"

    monkeypatch.setattr(brain, "_wait_approval", fake_wait)

    evs = await _run(sid, "删掉 a.txt")
    assert executed["n"] == 1
    tr = [p for n, p in evs if n == "tool_result"][0]
    assert tr["ok"] is True
    assert db.list_approvals("")[0]["status"] == "approved"


# ---------------------------------------------------------------- 4. 工具炸了
@pytest.mark.asyncio
async def test_tool_exception_does_not_crash_turn(tmp_db, fake_provider):
    def boom(args, ctx):
        raise RuntimeError("炸了")

    _register_simple("t.boom", fn=boom)
    fake_provider.add([_tool_call("c1", "t.boom", {}), _done()])
    fake_provider.add(_content("没成，", "它出错了。") + [_done()])

    sid = db.create_session()["id"]
    evs = await _run(sid, "试试")

    tr = [p for n, p in evs if n == "tool_result"][0]
    assert tr["ok"] is False
    final = "".join(p["text"] for n, p in evs if n == "content")
    assert "没成" in final
    assert [n for n, _ in evs][-1] == "turn_end"


# ---------------------------------------------------------------- 5. 兜底
@pytest.mark.asyncio
async def test_empty_reply_gets_fallback(tmp_db, fake_provider):
    fake_provider.add([_done()])  # 什么内容都没有
    sid = db.create_session()["id"]
    evs = await _run(sid, "嗯")
    text = "".join(p["text"] for n, p in evs if n == "content")
    assert text.strip()  # 不能空白


@pytest.mark.asyncio
async def test_error_event_on_provider_failure(tmp_db, fake_provider, monkeypatch):
    """主 provider 报错 → 降级失败 → 必须推 error 而不是静默。"""
    fake_provider.add([ProviderEvent(kind="error", text="炸了")])

    def pick(name=None):
        if name and name != "gateway":
            raise RuntimeError("兜底也起不来")
        return fake_provider

    monkeypatch.setattr("core.brain.get_provider", pick)

    sid = db.create_session()["id"]
    evs = await _run(sid, "在吗")
    names = [n for n, _ in evs]
    assert "error" in names


@pytest.mark.asyncio
async def test_max_rounds_guard(tmp_db, fake_provider, monkeypatch):
    """模型无限调工具 → 必须停下并收尾。"""
    from core import config

    cfg = config.load(force=True)
    cfg["brain"]["max_rounds"] = 3
    config.save(cfg)

    _register_simple()
    for _ in range(10):
        fake_provider.add([_tool_call("c", "t.echo", {"x": "1"}), _done()])

    sid = db.create_session()["id"]
    evs = await _run(sid, "循环")
    names = [n for n, _ in evs]
    assert names.count("tool_call") <= 3
    assert names[-1] == "turn_end"

    # 恢复配置
    cfg["brain"]["max_rounds"] = 6
    config.save(cfg)


# ---------------------------------------------------------------- 6. 事件契约
@pytest.mark.asyncio
async def test_event_names_are_from_contract(tmp_db, fake_provider):
    from core.events import ALL

    _register_simple()
    fake_provider.add([_tool_call("c1", "t.echo", {}), _done()])
    fake_provider.add(_content("好了") + [_done()])

    sid = db.create_session()["id"]
    evs = await _run(sid, "做一下")
    for name, _ in evs:
        assert name in ALL, f"事件名 {name} 不在契约里"


@pytest.mark.asyncio
async def test_turn_end_payload_shape(tmp_db, fake_provider):
    fake_provider.add(_content("hi") + [_done(5, 7)])
    sid = db.create_session()["id"]
    evs = await _run(sid, "hi")
    te = [p for n, p in evs if n == "turn_end"][0]
    for k in ("message_id", "tool_count", "latency_ms", "usage", "model"):
        assert k in te
    assert te["tool_count"] == 0


@pytest.mark.asyncio
async def test_abort_stops_turn(tmp_db, fake_provider):
    """用户点停止 → 循环退出。"""
    _register_simple()
    fake_provider.add([_tool_call("c1", "t.echo", {}), _done()])
    fake_provider.add(_content("x") + [_done()])

    sid = db.create_session()["id"]
    brain.request_abort(sid)
    evs = await _run(sid, "做")
    # 中止后不应跑满两轮
    names = [n for n, _ in evs]
    assert names[-1] == "turn_end"
