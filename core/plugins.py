"""GitHub 插件口：把 GitHub 仓库当成插件下载、校验、加载、卸载。

插件 = 一个 GitHub 仓库，结构：

    plugin.json          插件清单（必须）
    tools/*.py           工具模块（可选，格式与内置 tools/ 完全一致）

    plugin.json:
    {
      "id": "hello",              # 唯一，^[a-z0-9][a-z0-9_-]*$
      "name": "演示插件",
      "version": "1.0.0",
      "description": "做什么的",
      "author": "谁做的"
    }
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .paths import ROOT, ensure_dirs

logger = logging.getLogger("pccore.plugins")

PLUGINS_DIR = ROOT / "plugins"
INSTALLED_FILE = PLUGINS_DIR / "installed.json"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_REPO_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)?"
    r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)"
    r"(?:\.git)?(?:/.*)?$"
)
_BRANCH_RE = re.compile(r"^(.*?)@([A-Za-z0-9._/-]+)$")

_lock = threading.RLock()


def _ensure_dirs() -> None:
    ensure_dirs()
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)


def load_installed() -> list[dict]:
    _ensure_dirs()
    try:
        if not INSTALLED_FILE.exists():
            return []
        data = json.loads(INSTALLED_FILE.read_text(encoding="utf-8") or "[]")
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        logger.warning("插件清单损坏，按空处理：%s", INSTALLED_FILE)
        return []


def save_installed(items: list[dict]) -> None:
    _ensure_dirs()
    tmp = INSTALLED_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(INSTALLED_FILE)


def parse_repo(spec: str) -> tuple[str, str, str]:
    s = (spec or "").strip()
    if not s:
        raise ValueError("仓库地址为空")
    branch = "HEAD"
    m = _BRANCH_RE.match(s)
    if m and not s.startswith("http") and "/" in m.group(1):
        s, branch = m.group(1), m.group(2)
    if "/tree/" in s:
        head, _, tail = s.partition("/tree/")
        s = head
        branch = tail.split("/")[0]
    m = _REPO_RE.match(s)
    if not m:
        raise ValueError(f"认不出仓库地址：{spec!r}（给 owner/repo 或 GitHub 链接）")
    owner, repo = m.group(1), m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo, branch or "HEAD"


def clone_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}.git"


def codeload_url(owner: str, repo: str, branch: str) -> str:
    ref = branch if branch != "HEAD" else "main"
    return f"https://codeload.github.com/{owner}/{repo}/tar.gz/refs/heads/{ref}"


def _github_release_assets(owner: str, repo: str, tag: str | None = None) -> list[dict]:
    """列 GitHub Release 资产（走代理）。返回 [{name, browser_download_url}]。"""
    import json as _json
    import urllib.request

    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    if tag:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    proxy = _proxy_env().get("HTTPS_PROXY") or _proxy_env().get("https_proxy")
    handlers = [urllib.request.ProxyHandler({"https": proxy, "http": proxy})] if proxy else []
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "pc-core-plugin", "Accept": "application/vnd.github+json"})
    with opener.open(req, timeout=60) as resp:
        data = _json.loads(resp.read().decode("utf-8"))
    rel = data if isinstance(data, dict) else (data[0] if data else {})
    return rel.get("assets") or []


def _find_plugin_json(root: Path) -> Path | None:
    """在解压目录里找 plugin.json（根或一层子目录）。"""
    direct = root / "plugin.json"
    if direct.is_file():
        return direct
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "plugin.json").is_file():
                return child / "plugin.json"
    return None


def _download_and_install_release(spec: str) -> dict:
    """从 GitHub Release 下载 zip 资产并安装（spec 形如 owner/repo@v1.0.0）。"""
    import json as _json
    import tarfile
    import urllib.request
    import zipfile

    owner, repo, tag = parse_repo(spec)
    if tag == "HEAD":
        raise ValueError("Release 安装需要指定版本 tag：owner/repo@v1.0.0")
    _ensure_dirs()

    assets = _github_release_assets(owner, repo, tag)
    zips = [a for a in assets if a.get("name", "").endswith(".zip")]
    if not zips:
        raise ValueError(f"该 Release（{tag}）没有 .zip 资产；可用资产：{[a.get('name') for a in assets]}")
    asset = zips[0]
    dl_url = asset["browser_download_url"]

    tmp_zip = PLUGINS_DIR / f".dl-{int(time.time())}.zip"
    tmp_dir = PLUGINS_DIR / f".fetch-{owner}-{repo}-{int(time.time())}"
    try:
        proxy = _proxy_env().get("HTTPS_PROXY") or _proxy_env().get("https_proxy")
        handlers = [urllib.request.ProxyHandler({"https": proxy, "http": proxy})] if proxy else []
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(dl_url, headers={"User-Agent": "pc-core-plugin"})
        with opener.open(req, timeout=180) as resp, open(tmp_zip, "wb") as out:
            shutil.copyfileobj(resp, out)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp_zip) as zf:
            zf.extractall(tmp_dir)
        pj = _find_plugin_json(tmp_dir)
        if pj is None:
            raise ValueError("zip 里没有 plugin.json（插件清单）")
        raw = _json.loads(pj.read_text(encoding="utf-8") or "{}")
        manifest = validate_manifest(raw)
        pid = manifest["id"]
        dest = PLUGINS_DIR / pid
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        # 把 plugin.json 所在目录整体挪过去
        shutil.move(str(pj.parent), str(dest))
        with _lock:
            items = [it for it in load_installed() if it.get("id") != pid]
            item = {
                **manifest,
                "source": f"github:{owner}/{repo}@{tag}",
                "branch": tag,
                "installedAt": int(time.time() * 1000),
                "tools": reload_plugin_tools(pid),
            }
            items.append(item)
            save_installed(items)
        logger.info("插件已安装（Release）：%s v%s", pid, manifest["version"])
        return item
    finally:
        tmp_zip.unlink(missing_ok=True)
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def validate_manifest(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("plugin.json 必须是 JSON 对象")
    pid = str(data.get("id") or "").strip()
    if not _ID_RE.match(pid):
        raise ValueError(f"插件 id 不合法：{pid!r}（只允许小写字母/数字/-/_）")
    name = str(data.get("name") or pid).strip() or pid
    version = str(data.get("version") or "0.0.0").strip()
    desc = str(data.get("description") or "").strip()
    author = str(data.get("author") or "").strip()
    return {"id": pid, "name": name, "version": version, "description": desc, "author": author}


def _load_tool_module(path: Path, module_name: str) -> bool:
    from .toolbase import registry  # noqa: PLC0415

    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("插件工具无法构建 spec：%s", path)
            return False
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return registry.register(mod)
    except Exception as exc:  # noqa: BLE001
        logger.warning("插件工具加载失败 %s：%s: %s", path, type(exc).__name__, exc)
        return False


def load_plugin_tools(plugin_dir: Path, plugin_id: str) -> int:
    tools_dir = plugin_dir / "tools"
    if not tools_dir.is_dir():
        return 0
    n = 0
    for f in sorted(tools_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        mod_name = f"pccore_plugin_{plugin_id}_{f.stem}"
        if _load_tool_module(f, mod_name):
            n += 1
    return n


def reload_plugin_tools(plugin_id: str) -> int:
    d = PLUGINS_DIR / plugin_id
    if not d.is_dir():
        return 0
    return load_plugin_tools(d, plugin_id)


def _proxy_env() -> dict:
    """系统代理（127.0.0.1:7890）注入子进程环境。"""
    env = None
    try:
        import os
        import winreg  # Windows 专用；其它平台这里会失败，静默跳过

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        try:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
        finally:
            winreg.CloseKey(key)
        if enabled and server:
            proxy = f"http://{server}"
            env = {
                "HTTP_PROXY": proxy,
                "HTTPS_PROXY": proxy,
                "http_proxy": proxy,
                "https_proxy": proxy,
            }
    except Exception:
        return {}
    return env


def _run(cmd: list[str], cwd: Path | None = None, timeout_s: int = 300) -> str:
    import os

    env = {**os.environ, **_proxy_env()}
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout_s,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"下载超时（>{timeout_s}s）") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = "；".join(tail[-3:]) if tail else f"exit {proc.returncode}"
        raise RuntimeError(f"命令失败：{detail}")
    return proc.stdout or ""


def _fetch_repo(owner: str, repo: str, branch: str, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    url = clone_url(owner, repo)
    try:
        cmd = ["git", "clone", "--depth", "1", "--quiet", url, str(dest)]
        if branch != "HEAD":
            cmd = ["git", "clone", "--depth", "1", "--branch", branch, "--quiet", url, str(dest)]
        _run(cmd, timeout_s=300)
        git_dir = dest / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir, ignore_errors=True)
        return
    except Exception as exc:  # noqa: BLE001
        logger.info("git clone 失败（%s），回退 codeload tarball", exc)

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    try:
        import tarfile
        import urllib.request

        tarball = PLUGINS_DIR / f".tmp-{int(time.time())}.tar.gz"
        try:
            import os as _os

            _proxy = _proxy_env().get("HTTPS_PROXY") or _proxy_env().get("https_proxy")
            _handlers = [urllib.request.ProxyHandler({"https": _proxy, "http": _proxy})] if _proxy else []
            _opener = urllib.request.build_opener(*_handlers)
            req = urllib.request.Request(codeload_url(owner, repo, branch), headers={"User-Agent": "pc-core-plugin"})
            with _opener.open(req, timeout=120) as resp, open(tarball, "wb") as out:
                shutil.copyfileobj(resp, out)
            with tarfile.open(tarball) as tf:
                root = tf.getnames()[0].split("/")[0]
                tf.extractall(dest)
            extracted = dest / root
            if extracted.is_dir():
                for child in list(extracted.iterdir()):
                    shutil.move(str(child), str(dest / child.name))
                shutil.rmtree(extracted, ignore_errors=True)
        finally:
            tarball.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"下载失败（git 与 tarball 都不行）：{exc}") from exc


def install(spec: str) -> dict:
    owner, repo, branch = parse_repo(spec)
    # 带 @tag 的走 GitHub Release zip 资产
    if branch != "HEAD":
        return _download_and_install_release(spec)
    _ensure_dirs()
    tmp = PLUGINS_DIR / f".fetch-{owner}-{repo}-{int(time.time())}"
    try:
        _fetch_repo(owner, repo, branch, tmp)
    except Exception as exc:
        raise RuntimeError(f"下载 {owner}/{repo} 失败：{exc}") from exc

    manifest_path = tmp / "plugin.json"
    if not manifest_path.is_file():
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError("仓库里没有 plugin.json（插件清单）")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8") or "{}")
        manifest = validate_manifest(raw)
    except json.JSONDecodeError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError(f"plugin.json 不是合法 JSON：{exc}") from exc
    except ValueError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    pid = manifest["id"]
    dest = PLUGINS_DIR / pid
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.move(str(tmp), str(dest))

    with _lock:
        items = [it for it in load_installed() if it.get("id") != pid]
        item = {
            **manifest,
            "source": f"github:{owner}/{repo}",
            "branch": branch,
            "installedAt": int(time.time() * 1000),
            "tools": reload_plugin_tools(pid),
        }
        items.append(item)
        save_installed(items)
    logger.info("插件已安装：%s v%s（tools=%d, source=%s/%s）", pid, manifest["version"], item["tools"], owner, repo)
    return item


def uninstall(pid: str) -> dict:
    _ensure_dirs()
    if not _ID_RE.match(pid):
        raise ValueError(f"插件 id 不合法：{pid!r}")
    dest = PLUGINS_DIR / pid
    with _lock:
        items = load_installed()
        target = next((it for it in items if it.get("id") == pid), None)
        if target is None and not dest.exists():
            raise ValueError(f"没有这个插件：{pid}")
        try:
            from .toolbase import registry  # noqa: PLC0415

            removed = registry.unregister_prefix(f"pc.{pid}.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("卸载时撤销工具失败：%s", exc)
            removed = 0
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        items = [it for it in items if it.get("id") != pid]
        save_installed(items)
    logger.info("插件已卸载：%s（撤销工具 %d 个）", pid, removed)
    return {"id": pid, "removedTools": removed}


def list_plugins() -> list[dict]:
    items = load_installed()
    for it in items:
        pid = it.get("id") or ""
        d = PLUGINS_DIR / pid if _ID_RE.match(pid) else None
        it["onDisk"] = bool(d is not None and d.is_dir())
        it["pluginJsonOk"] = bool(d is not None and (d / "plugin.json").is_file())
    return items


def boot_load_all() -> int:
    _ensure_dirs()
    total = 0
    for it in load_installed():
        pid = it.get("id") or ""
        if not _ID_RE.match(pid):
            continue
        d = PLUGINS_DIR / pid
        if not (d / "plugin.json").is_file():
            logger.warning("插件 %s 缺 plugin.json，跳过", pid)
            continue
        n = reload_plugin_tools(pid)
        total += n
        if n:
            logger.info("插件工具加载：%s → %d 个", pid, n)
    return total


# ------------------------------------------------------------------ 市场目录

def market_index(url: str | None = None) -> dict:
    """拉取插件市场目录（JSON）。默认用社区市场。

    优先用 `gh api`（走已登录 GitHub 凭据，代理友好）；失败再回退 HTTPS。
    """
    import json as _json
    import urllib.request

    if url is None:
        url = "https://raw.githubusercontent.com/Wu-love-han/pc-core-plugin-demo/main/market.json"

    # 走 gh api：把 raw.githubusercontent.com/owner/repo/branch/path 转成 repos/owner/repo/contents/path
    text = None
    m = re.match(r"^https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$", url)
    if m:
        owner, repo, branch, path = m.groups()
        try:
            text = _run(
                ["gh", "api", f"repos/{owner}/{repo}/contents/{path}", "-H", "Accept: application/vnd.github.raw"],
                timeout_s=60,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("gh api 拉市场失败（%s），回退 HTTPS", exc)

    if text is None:
        proxy = _proxy_env().get("HTTPS_PROXY") or _proxy_env().get("https_proxy")
        handlers = [urllib.request.ProxyHandler({"https": proxy, "http": proxy})] if proxy else []
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(url, headers={"User-Agent": "pc-core-plugin"})
        with opener.open(req, timeout=60) as resp:
            text = resp.read().decode("utf-8")

    data = _json.loads(text)
    return data if isinstance(data, dict) else {"plugins": data}


