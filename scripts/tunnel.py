"""小伴 · 公网隧道（Cloudflare 快速隧道）

用途：人在外面、连不上 Tailscale 时，用公网地址访问控制台。
安全：
- 只暴露控制台（8771），它本身有 PIN + 登录限流
- 不暴露主 API（8770）
- URL 每次重启都变，且是随机字符串，别人猜不到

用法：
    python scripts/tunnel.py          # 前台跑，会打印公网地址
    python scripts/tunnel.py --bg     # 后台跑，地址写进 data/tunnel_url.txt
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL_FILE = ROOT / "data" / "tunnel_url.txt"
LOG_FILE = ROOT / "logs" / "tunnel.log"

CF_CANDIDATES = [
    Path.home() / ".dsh" / "profiles" / "desktop" / "node_modules" / ".bin" / "cloudflared.CMD",
    Path.home() / ".dsh" / "profiles" / "desktop" / "node_modules" / "cloudflared" / "bin" / "cloudflared.exe",
]


def find_cloudflared() -> str | None:
    for p in CF_CANDIDATES:
        if p.exists():
            return str(p)
    # 退而求其次：PATH 里找
    import shutil

    return shutil.which("cloudflared")


def main() -> int:
    target_port = 8771
    for arg in sys.argv[1:]:
        if arg.isdigit():
            target_port = int(arg)

    cf = find_cloudflared()
    if not cf:
        print("[X] 没找到 cloudflared")
        print("    可以 pip install cloudflared 或者从 Cloudflare 官网下载")
        return 1

    URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  小伴 · 公网隧道")
    print("=" * 60)
    print(f"  目标：http://127.0.0.1:{target_port}（控制台，PIN 保护）")
    print("  正在建立隧道…")
    print()

    cmd = [cf, "tunnel", "--url", f"http://127.0.0.1:{target_port}", "--no-autoupdate"]
    env = dict(os.environ)
    env.setdefault("NO_COLOR", "1")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=env)

    url = ""
    log = LOG_FILE.open("a", encoding="utf-8")
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            log.write(line)
            log.flush()
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and not url:
                url = m.group(0)
                URL_FILE.write_text(url + "\n", encoding="utf-8")
                print("=" * 60)
                print(f"  公网地址：{url}")
                print("=" * 60)
                print()
                print("  手机/外面任何浏览器打开这个地址，输 PIN 就能进")
                print(f"  PIN：在 config.json 的 server.console_pin")
                print()
                print("  ⚠ 这是公网地址，别人知道 URL 也能试 PIN（已限流：错 5 次锁 10 分钟）")
                print("  按 Ctrl+C 停止")
                print()
            if os.environ.get("TUNNEL_ONCE") and url:
                # 后台模式：拿到地址就退出，让调用方自己管进程
                break
    except KeyboardInterrupt:
        pass
    finally:
        log.close()
        if proc.poll() is None:
            proc.terminate()

    return 0 if url else 2


if __name__ == "__main__":
    sys.exit(main())
