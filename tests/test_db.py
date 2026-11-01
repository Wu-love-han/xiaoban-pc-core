"""数据层测试：表建得对、增删改查对、级联删除对。"""

from __future__ import annotations


def test_schema_created(tmp_db):
    s = tmp_db.stats()
    for k in ("sessions", "messages", "tool_runs", "approvals", "events", "memories"):
        assert k in s
        assert s[k] == 0


def test_session_crud(tmp_db):
    s = tmp_db.create_session("测试会话")
    assert s["id"].startswith("s_")
    got = tmp_db.get_session(s["id"])
    assert got and got["title"] == "测试会话"

    tmp_db.touch_session(s["id"], title="改名了")
    assert tmp_db.get_session(s["id"])["title"] == "改名了"

    items = tmp_db.list_sessions()
    assert len(items) == 1 and items[0]["msg_count"] == 0

    tmp_db.delete_session(s["id"])
    assert tmp_db.get_session(s["id"]) is None


def test_messages_and_history(tmp_db):
    s = tmp_db.create_session()
    sid = s["id"]
    tmp_db.add_message(sid, "user", "你好")
    tmp_db.add_message(sid, "assistant", "在呢")
    tmp_db.add_message(sid, "user", "今天累")

    msgs = tmp_db.list_messages(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]

    hist = tmp_db.history_for_model(sid, turns=8)
    assert len(hist) == 3
    assert hist[0] == {"role": "user", "content": "你好"}


def test_tool_calls_roundtrip(tmp_db):
    """这是新架构的关键证据：每轮工具调用必须能落库查回来。"""
    s = tmp_db.create_session()
    sid = s["id"]
    calls = [{"call_id": "c1", "name": "pc.list_dir", "args": {"path": "E:\\WH"}}]
    tmp_db.add_message(sid, "assistant", "看了下", tool_calls=calls)
    got = tmp_db.list_messages(sid)[0]
    assert got["tool_calls"] == calls


def test_tool_runs(tmp_db):
    s = tmp_db.create_session()
    sid = s["id"]
    tmp_db.add_tool_run(sid, "c1", "pc.list_dir", {"path": "x"}, True, "ok", 12)
    runs = tmp_db.list_tool_runs(sid)
    assert len(runs) == 1
    assert runs[0]["name"] == "pc.list_dir"
    assert runs[0]["ok"] is True
    assert runs[0]["args"] == {"path": "x"}


def test_approval_lifecycle(tmp_db):
    s = tmp_db.create_session()
    sid = s["id"]
    ap = tmp_db.create_approval(sid, "c9", "pc.delete", {"path": "a.txt"})
    assert ap["status"] == "pending"
    assert tmp_db.get_approval(ap["id"])["args"]["path"] == "a.txt"

    assert tmp_db.decide_approval(ap["id"], "approved") is True
    # 第二次必须失败（防重复点击）
    assert tmp_db.decide_approval(ap["id"], "denied") is False
    assert tmp_db.get_approval(ap["id"])["status"] == "approved"

    assert tmp_db.list_approvals("pending") == []


def test_approval_expiry(tmp_db):
    s = tmp_db.create_session()
    ap = tmp_db.create_approval(s["id"], "c1", "pc.delete", {})
    # 让"超时阈值"为 0，立刻过期
    n = tmp_db.expire_approvals(older_than_ms=-1)
    assert n == 1
    assert tmp_db.get_approval(ap["id"])["status"] == "expired"


def test_delete_session_cascades(tmp_db):
    s = tmp_db.create_session()
    sid = s["id"]
    tmp_db.add_message(sid, "user", "hi")
    tmp_db.add_tool_run(sid, "c1", "t", {}, True, "o", 1)
    tmp_db.create_approval(sid, "c1", "t", {})
    tmp_db.add_event("x", {}, sid)

    tmp_db.delete_session(sid)
    assert tmp_db.list_messages(sid) == []
    assert tmp_db.list_tool_runs(sid) == []
    assert tmp_db.list_events(session_id=sid) == []
    assert tmp_db.list_approvals("") == []


def test_memory_remember_recall(tmp_db):
    tmp_db.remember("用户名字", "小王")
    tmp_db.remember("面试", "下周三下午两点")
    tmp_db.remember("用户名字", "小王（更新）")

    items = tmp_db.recall("名字")
    assert any("名字" in it["key"] for it in items)
    # 更新而不是新增
    assert len(tmp_db.list_memories()) == 2
    name_rec = [m for m in tmp_db.list_memories() if m["key"] == "用户名字"][0]
    assert "更新" in name_rec["value"]


def test_memory_forget(tmp_db):
    r = tmp_db.remember("临时", "x")
    assert tmp_db.forget(r["id"]) is True
    assert tmp_db.list_memories() == []


def test_events_order(tmp_db):
    s = tmp_db.create_session()
    tmp_db.add_event("a", {"i": 1}, s["id"])
    tmp_db.add_event("b", {"i": 2}, s["id"])
    evs = tmp_db.list_events(session_id=s["id"])
    # 返回是倒序（最新在前）
    assert [e["kind"] for e in evs] == ["b", "a"]
