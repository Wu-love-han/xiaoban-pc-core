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


ADB_CANDIDATES = [
    r"C:\Users\Wh987\.phonemcp\platform-tools\adb.exe",
    "adb",
]


_last_reverse = {"at": 0.0, "ok": False}


def ensure_adb_reverse(force: bool = False) -> None:
    """USB 连着时，让手机能访问电脑的 127.0.0.1（反向端口转发）。

    这样手机 App 用 http://127.0.0.1:8770 就能连上，不依赖 WiFi/Tailscale。
    """
    import shutil

    now = time.time()
    if not force and now - _last_reverse["at"] < 60:
        return
    _last_reverse["at"] = now

    adb = None
    for c in ADB_CANDIDATES:
        if c == "adb":
            adb = shutil.which("adb")
        elif Path(c).exists():
            adb = c
        if adb:
            break
    if not adb:
        return
    try:
        dev = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=15)
        if "device" not in (dev.stdout or ""):
            _last_reverse["ok"] = False
            return
        for port in ("8770", "8771"):
            subprocess.run([adb, "reverse", f"tcp:{port}", f"tcp:{port}"],
                           capture_output=True, timeout=15)
        if not _last_reverse["ok"]:
            log("adb reverse 已设置（8770 / 8771）")
            _last_reverse["ok"] = True
    except Exception as exc:  # noqa: BLE001
        log(f"adb reverse 失败：{exc}")


def start_console() -> subprocess.Popen | None:
    """控制台是独立进程（端口 8771）：AI 的工具够不到它。"""
    script = ROOT / "console" / "server.py"
    if not script.exists():
        log("没找到控制台脚本，跳过")
        return None
    log("启动控制台 0.0.0.0:8771")
    try:
        return subprocess.Popen([PYTHON, str(script)], cwd=str(ROOT))
    except Exception as exc:  # noqa: BLE001
        log(f"控制台启动失败：{exc}")
        return None


def main() -> None:
    global child, crashes
    log("=== 小伴守护进程启动 ===")
    console = start_console()
    child = start()
    time.sleep(6)
    ensure_adb_reverse()
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
            # 还活着，继续等；顺便维持 adb reverse（手机拔插后要重设）
            ensure_adb_reverse()
            continue
        except KeyboardInterrupt:
            log("收到中断，关闭后端")
            try:
                child.terminate()
                child.wait(timeout=10)
            except Exception:
                child.kill()
            try:
                if console:
                    console.terminate()
            except Exception:
                pass
            break


if __name__ == "__main__":
    main()
