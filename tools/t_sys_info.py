"""sys.info：CPU / 内存 / 磁盘 / 显卡 / 系统版本。

为什么不用 psutil 硬依赖：这个工程可能跑在只装了标准库的解释器上（项目 .venv 就是空的），
工具层不许因为缺一个三方包就整体加载失败。所以 psutil 有就用，没有就走
ctypes/shutil/platform 的等价路径，结果一样能用。
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import _common as C


# ---------------------------------------------------------------- 内存
def _mem_windows() -> tuple[int, int] | None:
    """用 Win32 GlobalMemoryStatusEx 拿 (总, 可用) 字节。"""
    try:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return int(st.ullTotalPhys), int(st.ullAvailPhys)
    except Exception:  # noqa: BLE001
        return None


def _mem_posix() -> tuple[int, int] | None:
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition(":")
            info[k.strip()] = int(v.strip().split()[0]) * 1024
        return info.get("MemTotal", 0), info.get("MemAvailable", 0)
    except Exception:  # noqa: BLE001
        return None


def _memory() -> tuple[int, int] | None:
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        return int(vm.total), int(vm.available)
    except Exception:  # noqa: BLE001
        pass
    return _mem_windows() if platform.system() == "Windows" else _mem_posix()


# ---------------------------------------------------------------- 磁盘
def _disks() -> list[str]:
    """列固定盘的使用率。只取存在的那几个盘，跳过光驱/网络盘。"""
    out = []
    if platform.system() == "Windows":
        roots = [f"{d}:\\" for d in "CDEFGH" if Path(f"{d}:\\").exists()]
    else:
        roots = ["/"]
    for root in roots:
        try:
            u = shutil.disk_usage(root)
        except OSError:
            continue
        pct = int(u.used * 100 / u.total) if u.total else 0
        out.append(f"{root} {C.human_size(u.free)}可用/{C.human_size(u.total)}({pct}%用)")
    return out


# ---------------------------------------------------------------- 显卡
def _gpu() -> str:
    """nvidia-smi 拿显卡名和显存。没装/没卡就返回空串，不算错误。"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"],
            capture_output=True,
            timeout=6,
            encoding="utf-8",
            errors="replace",
        )
        line = (r.stdout or "").strip().splitlines()
        if r.returncode == 0 and line:
            name, total, used = [x.strip() for x in line[0].split(",")]
            return f"{name} {used}/{total}"
    except Exception:  # noqa: BLE001
        pass
    return ""


def _cpu_name() -> str:
    """Windows 上 platform.processor() 只给 "Intel64 Family..."，从注册表能拿到型号。"""
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except Exception:  # noqa: BLE001
            pass
    return platform.processor() or platform.machine() or "未知"


def run(args: dict, ctx: Any) -> dict:
    os_name = f"{platform.system()} {platform.release()}"
    build = platform.version()
    cpu = _cpu_name()
    cores = os.cpu_count() or 0

    parts = [
        f"系统 {os_name}（{build}）",
        f"CPU {cpu} / {cores} 核",
    ]

    mem = _memory()
    if mem and mem[0]:
        total, avail = mem
        pct = int((total - avail) * 100 / total)
        parts.append(f"内存 {C.human_size(avail)}可用/{C.human_size(total)}（{pct}%用）")

    disks = _disks()
    if disks:
        parts.append("磁盘 " + "；".join(disks))

    gpu = _gpu()
    if gpu:
        parts.append(f"显卡 {gpu}")

    parts.append(f"Python {platform.python_version()} / {platform.machine()}")
    return C.ok(" | ".join(parts))


TOOL = {
    "name": "sys.info",
    "title": "看机器状况",
    "desc": "查这台电脑的 CPU、内存、磁盘、显卡和系统版本。想知道机器累不累、还有多少空间时用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {},
    },
    "run": C.guard(run),
}
