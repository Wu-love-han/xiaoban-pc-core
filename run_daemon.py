"""小伴守护进程：崩了自动重启（抗段错误）。

用法：
    .venv\\Scripts\\python.exe run_daemon.py

为什么需要：
    Windows 上 uvicorn 偶发 Segmentation fault（SQLite C 扩展/Winsock 信号），
    Python 层捕获不到，只能外层重启。
    每 3 秒检查一次，进程退出就重新拉起，并记录崩溃次数。

安全：只重启自己拉起的子进程，不碰别人的 8770。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")
if not Path(PYTHON).exists():
    PYTHON = sys.executable

HOST = os.environ.get("PCORE_HOST", "127.0.0.1")
PORT = os.environ.get("PCORE_PORT", "8770")
LOG = ROOT / "logs" / "daemon.log"

crashes = 0
child: subprocess.Popen | None = None


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def start() -> subprocess.Popen:
    cmd = [
        PYTHON, "-m", "uvicorn", "server.main:app",
        "--host", HOST, "--port", PORT, "--app-dir", str(ROOT),
    ]
    log(f"启动后端 {HOST}:{PORT}")
    return subprocess.Popen(cmd, cwd=str(ROOT))


def main() -> None:
    global child, crashes
    log("=== 小伴守护进程启动 ===")
    child = start()
    while True:
        try:
            code = child.wait(timeout=3)
            # 子进程退出
            if code == 0:
                log("后端正常退出，守护进程结束")
                break
            crashes += 1
            log(f"后端异常退出（code={code}），第 {crashes} 次重启")
            if crashes > 50:
                log("重启超过 50 次，放弃")
                break
            time.sleep(2)
            child = start()
        except subprocess.TimeoutExpired:
            # 还活着，继续等
            continue
        except KeyboardInterrupt:
            log("收到中断，关闭后端")
            try:
                child.terminate()
                child.wait(timeout=10)
            except Exception:
                child.kill()
            break


if __name__ == "__main__":
    main()
