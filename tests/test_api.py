"""API 层测试：用 TestClient 打路由，不起真服务。

注意：server 由队友并行开发。这里先写「契约级」断言，
如果 server 还没就绪，整个模块 skip 而不是失败。
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

try:
    from server.main import app  # noqa: F401
    HAS_APP = True
except Exception:  # noqa: BLE001
    HAS_APP = False

pytestmark = pytest.mark.skipif(not HAS_APP, reason="server 尚未就绪")


@pytest.fixture()
def client(tmp_db, monkeypatch):
    from fastapi.testclient import TestClient

    from core import config

    cfg = config.load(force=True)
    cfg["server"]["auth_token"] = ""
    config.save(cfg)

    from server.main import app as _app

    return TestClient(_app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d.get("ok") is True
    for k in ("provider", "model", "tools"):
        assert k in d


def test_tools_list(client):
    r = client.get("/api/tools")
    assert r.status_code == 200
    items = r.json()["items"]
    assert isinstance(items, list)
    names = {t["name"] for t in items}
    assert "pc.list_dir" in names


def test_session_crud(client):
    r = client.post("/api/sessions", json={"title": "t"})
    assert r.status_code == 200
    sid = r.json()["id"]

    r = client.get("/api/sessions")
    assert any(s["id"] == sid for s in r.json()["items"])

    r = client.get(f"/api/sessions/{sid}/messages")
    assert r.status_code == 200

    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200


def test_config_redacted(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    d = r.json()
    tok = (d.get("server") or {}).get("auth_token")
    assert tok in ("", "***")


def test_events_endpoint(client):
    r = client.get("/api/events?limit=5")
    assert r.status_code == 200
    assert isinstance(r.json()["items"], list)


def test_approvals_pending_empty(client):
    r = client.get("/api/approvals?status=pending")
    assert r.status_code == 200
    assert isinstance(r.json()["items"], list)


def test_chat_sse_frames_are_valid(client, monkeypatch):
    """SSE 每帧必须是 event:/data: 两行，data 能 JSON.parse。"""
    from core import brain

    async def fake_turn(session_id, text, **kw):
        yield ("content", {"text": "你"})
        yield ("content", {"text": "好"})
        yield ("turn_end", {"message_id": 1, "tool_count": 0, "latency_ms": 5,
                            "usage": {"in": 1, "out": 2}, "model": "m"})

    monkeypatch.setattr(brain, "run_turn", fake_turn)

    r = client.post("/api/chat", json={"text": "你好"})
    assert r.status_code == 200
    body = r.text
    assert "event: content" in body
    assert "event: turn_end" in body
    for block in [b for b in body.split("\n\n") if b.strip().startswith("event:")]:
        lines = [l for l in block.splitlines() if l.strip()]
        ev = [l for l in lines if l.startswith("event:")][0][6:].strip()
        data = [l for l in lines if l.startswith("data:")][0][5:].strip()
        json.loads(data)  # 必须能解析
        assert ev
