"""GitHub 连接：搜索 / 仓库详情 / Release / 账户状态。

走本机已登录的 `gh` CLI（keyring 凭据），所以：
- 不受匿名 API 限流
- 私有仓库也能读
- 不需要在软件里再存一份 token

用途（用户需求）：
    "要什么插件，通过这个搜索，然后我可以登录我的账户"
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger("pccore.github")

TIMEOUT = 45


def _proxy_env() -> dict:
    """继承系统代理（Windows 注册表），让 gh 子进程能走代理。"""
    env = dict(os.environ)
    try:
        import winreg  # Windows only

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        try:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
        finally:
            winreg.CloseKey(key)
        if enabled and server:
            proxy = f"http://{server}"
            env.setdefault("HTTP_PROXY", proxy)
            env.setdefault("HTTPS_PROXY", proxy)
            env.setdefault("http_proxy", proxy)
            env.setdefault("https_proxy", proxy)
    except Exception:  # noqa: BLE001
        pass
    return env


def _gh(args: list[str], timeout: int = TIMEOUT) -> tuple[int, str, str]:
    """跑 gh 命令，返回 (rc, stdout, stderr)。"""
    try:
        p = subprocess.run(
            ["gh"] + args,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=_proxy_env(),
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", "没装 GitHub CLI（gh）"
    except subprocess.TimeoutExpired:
        return 124, "", "gh 命令超时（网络或代理问题）"


def _gh_json(args: list[str]) -> tuple[bool, Any]:
    rc, out, err = _gh(args)
    if rc != 0:
        return False, (err or out or f"gh 退出码 {rc}").strip()[:300]
    try:
        return True, json.loads(out or "null")
    except json.JSONDecodeError as exc:
        return False, f"gh 返回的不是 JSON：{exc}"


# ---------------------------------------------------------------- 账户

def status() -> dict:
    """GitHub 账户状态。"""
    rc, out, err = _gh(["auth", "status"])
    text = (out or "") + (err or "")
    logged_in = rc == 0 and "Logged in" in text

    login, name, scopes = "", "", ""
    if logged_in:
        ok, data = _gh_json(["api", "user"])
        if ok and isinstance(data, dict):
            login = data.get("login") or ""
            name = data.get("name") or ""
    # 从 auth status 里抠 scopes
    import re

    m = re.search(r"Token scopes:\s*(.+)", text)
    if m:
        scopes = m.group(1).strip()

    return {
        "loggedIn": logged_in,
        "login": login,
        "name": name,
        "scopes": scopes,
        "hint": "" if logged_in else "在终端运行 `gh auth login` 登录 GitHub 账户（支持浏览器授权）",
        "raw": text.strip()[:400],
    }


# ---------------------------------------------------------------- 搜索

def search(query: str, sort: str = "stars", limit: int = 20) -> dict:
    """搜 GitHub 仓库。query 可以是关键词、topic:xxx、user:xxx。"""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "搜索词为空"}
    limit = max(1, min(50, int(limit)))
    sort = sort if sort in ("stars", "updated", "forks", "help-wanted-issues") else "stars"

    import urllib.parse

    path = f"search/repositories?q={urllib.parse.quote(q)}&sort={sort}&per_page={limit}"
    ok, data = _gh_json(["api", path])
    if not ok:
        return {"ok": False, "error": str(data)}

    items = []
    for it in (data or {}).get("items", []):
        items.append({
            "fullName": it.get("full_name", ""),
            "description": (it.get("description") or "")[:160],
            "stars": it.get("stargazers_count", 0),
            "language": it.get("language") or "",
            "updatedAt": (it.get("updated_at") or "")[:10],
            "topics": (it.get("topics") or [])[:6],
            "archived": bool(it.get("archived")),
        })
    return {"ok": True, "items": items, "count": len(items), "query": q}


def search_plugins(query: str = "", limit: int = 20) -> dict:
    """优先搜小伴/DSH 生态插件，不够再逐级放宽。

    顺序：
      1. `<q> topic:dsh-plugin`（最精准）
      2. `<q> dsh plugin`（关键词）
      3. `<q>`（通用兜底，结果里标注可能不是插件）
    """
    q = (query or "").strip()

    attempts = []
    if q:
        attempts = [f"{q} topic:dsh-plugin", f"{q} dsh plugin", q]
    else:
        attempts = ["topic:dsh-plugin", "dsh plugin"]

    for i, full in enumerate(attempts):
        res = search(full, limit=limit)
        items = res.get("items") or []
        if len(items) >= 3 or (i == len(attempts) - 1):
            # 标注来源精度
            for it in items:
                it["matchLevel"] = ("精准" if i == 0 else "相关" if i == 1 else "通用")
            res["query"] = full
            return res
    return {"ok": False, "items": [], "error": "搜索失败"}


# ---------------------------------------------------------------- 仓库详情

def repo_info(full_name: str) -> dict:
    fn = (full_name or "").strip()
    if "/" not in fn:
        return {"ok": False, "error": "格式要是 owner/repo"}
    ok, data = _gh_json(["api", f"repos/{fn}"])
    if not ok:
        return {"ok": False, "error": str(data)}
    if not isinstance(data, dict):
        return {"ok": False, "error": "仓库不存在"}
    return {
        "ok": True,
        "repo": {
            "fullName": data.get("full_name"),
            "description": (data.get("description") or "")[:300],
            "stars": data.get("stargazers_count", 0),
            "defaultBranch": data.get("default_branch") or "main",
            "private": bool(data.get("private")),
            "topics": (data.get("topics") or [])[:8],
            "htmlUrl": data.get("html_url"),
        },
    }


def releases(full_name: str, limit: int = 10) -> dict:
    fn = (full_name or "").strip()
    if "/" not in fn:
        return {"ok": False, "error": "格式要是 owner/repo"}
    ok, data = _gh_json(["api", f"repos/{fn}/releases?per_page={limit}"])
    if not ok:
        return {"ok": False, "error": str(data)}
    out = []
    for r in (data or []):
        assets = [
            {"name": a.get("name"), "size": a.get("size"), "url": a.get("browser_download_url")}
            for a in (r.get("assets") or [])
        ]
        out.append({
            "tag": r.get("tag_name"),
            "name": r.get("name") or r.get("tag_name"),
            "publishedAt": (r.get("published_at") or "")[:10],
            "assets": assets,
        })
    return {"ok": True, "items": out, "count": len(out)}


def login_hint() -> dict:
    """登录引导（真正的登录要在终端做，支持浏览器授权）。"""
    return {
        "ok": True,
        "commands": [
            "gh auth login",              # 交互式，选 GitHub.com → HTTPS → 浏览器授权
            "gh auth login --web",        # 直接开浏览器
            "gh auth switch",             # 多账号切换
        ],
        "note": "登录后本软件自动用该账户（走系统 keyring，软件不存 token）",
    }
