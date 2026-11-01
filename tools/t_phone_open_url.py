"""手机工具：经 Tailscale 内网调手机 Agent（只读/写白名单，危险永久拒）。

手机端权限底线见 E:\WH\phone-agent\agent.py。
"""

from __future__ import annotations

import json
import urllib.request

from core import config as cfg_mod

AGENT_TIMEOUT = 20


def _cfg(key: str, default):
    phone = (cfg_mod.load().get("phone") or {})
    return phone.get(key, default)


def _call(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{_cfg('agent_url', 'http://100.115.152.111:9100').rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    token = str(_cfg("token", "") or "").strip()
    if token:
        req.add_header("X-Agent-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=AGENT_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"手机 Agent 不可达：{exc}"}


def _get(path: str) -> dict:
    return _call("GET", path)


def _post(path: str, body: dict) -> dict:
    return _call("POST", path, body)


TOOL = {
    "name": "phone.open_url",
    "title": "手机打开链接",
    "desc": "在手机浏览器打开一个 http/https 链接",
    "danger": False,
    "params": {'type': 'object', 'properties': {'url': {'type': 'string', 'description': 'http/https 链接'}}},
    "run": lambda args, ctx: _post('/api/open_url', {'url': args.get('url', '')}),
}
