"""测试夹具。

关键：每个测试用独立的临时数据库和临时 workspace，
绝不碰生产 data/pccore.db。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """把 db 指向临时文件。"""
    from core import db, paths

    dbfile = tmp_path / "test.db"
    monkeypatch.setattr(paths, "DB_FILE", dbfile)
    monkeypatch.setattr(db, "DB_FILE", dbfile)
    # 清掉线程局部连接，强制用新路径重连
    if hasattr(db._local, "conn"):
        try:
            db._local.conn.close()
        except Exception:  # noqa: BLE001
            pass
        del db._local.conn
    db.init()
    yield db
    if hasattr(db._local, "conn"):
        try:
            db._local.conn.close()
        except Exception:  # noqa: BLE001
            pass
        del db._local.conn


@pytest.fixture()
def fake_provider(monkeypatch):
    """把 provider 换成可编排的假实现，用来测大脑循环而不打真实模型。

    用法：
        fake = fake_provider()
        fake.add([ProviderEvent(kind="content", text="hi")])
    """
    from core.providers import base as pbase

    class Scripted:
        name = "scripted"

        def __init__(self):
            self.scripts: list[list[pbase.ProviderEvent]] = []
            self.calls: list[dict] = []

        def add(self, events):
            self.scripts.append(list(events))
            return self

        async def stream(self, messages, tools, **kw):
            self.calls.append({"messages": messages, "tools": tools, **kw})
            if not self.scripts:
                yield pbase.ProviderEvent(kind="content", text="(no script)")
                yield pbase.ProviderEvent(kind="done", usage={"in": 0, "out": 0})
                return
            for ev in self.scripts.pop(0):
                yield ev

        async def health(self):
            return {"ok": True, "provider": "scripted"}

    fake = Scripted()
    monkeypatch.setattr("core.brain.get_provider", lambda *a, **k: fake)
    return fake
