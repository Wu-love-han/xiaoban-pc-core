"""路径常量。所有模块都从这里取路径，不许自己拼。

为什么单独一个文件：E: 是 exFAT，C: 是 NTFS，两个盘行为不一样；
统一在这里定义，改一处全项目跟着改。
"""

from __future__ import annotations

from pathlib import Path

# core/paths.py → 上两级就是工程根
ROOT: Path = Path(__file__).resolve().parent.parent

DOCS = ROOT / "docs"
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
WORKSPACE = ROOT / "workspace"
TOOLS_DIR = ROOT / "tools"
WEB_DIR = ROOT / "web"
TESTS_DIR = ROOT / "tests"

CONFIG_FILE = CONFIG_DIR / "config.json"
DB_FILE = DATA_DIR / "pccore.db"
PERSONA_FILE = DOCS / "PERSONA.md"

# 内置默认配置。config.json 里缺的键从这里补，所以升级不会炸。
DEFAULT_CONFIG: dict = {
    "server": {
        "host": "127.0.0.1",
        "port": 8770,
        # 留空 = 不校验（本机开发）。要给手机/局域网用时必须填，并改 host 为 0.0.0.0
        "auth_token": "",
    },
    "brain": {
        # gateway = 本机 Magpie 网关（默认大脑，支持原生 function calling）
        # ollama  = 本地 Ollama 兜底
        "provider": "gateway",
        "model": "deepseek/deepseek-flash",
        "fallback_provider": "ollama",
        "fallback_model": "qwen2.5:7b",
        "reasoning": "none",
        "temperature": 0.8,
        "top_p": 0.92,
        "max_tokens": 1200,
        "max_rounds": 12,  # 多步任务需要更多轮
        "history_turns": 8,
        "approval_timeout_s": 300,
    },
    "providers": {
        "gateway": {
            "base_url": "http://127.0.0.1:3425/v1",
            "api_key": "",
            "timeout_s": 180,
        },
        "ollama": {
            "base_url": "http://127.0.0.1:11434",
            "timeout_s": 300,
            "num_ctx": 8192,
        },
        # 手机 App 本地能力服务（v2 App 内置，端口 9123）
        # 优先 Tailscale（异地也能用），回落局域网
        "phone": {
            "cap_urls": [
                "http://100.115.152.111:9123",
                "http://172.30.188.163:9123",
            ],
            "token": "",
            "timeout_s": 8,
        },
        # DeepSeek 官方 API：填上 api_key 后，把 brain.provider 改成 "deepseek" 即可
        # 申请地址 https://platform.deepseek.com/api_keys
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "",
            "timeout_s": 180,
        },
    },
    "tools": {
        "enabled": [],          # 空 = 全部启用
        # 只读命令白名单（小伴反馈：太窄了，很多只读命令跑不了，已放宽）
        "shell_whitelist": [
            # 目录 / 文件查看
            "dir", "ls", "type", "cat", "more", "head", "tail", "where", "which",
            "tree", "find", "grep", "findstr", "wc", "sort", "uniq",
            # 系统信息
            "whoami", "hostname", "systeminfo", "ver", "date", "time", "set",
            "ipconfig", "ifconfig", "ping", "nslookup", "netstat", "route", "arp",
            "wmic", "sc query", "net use", "net view", "net share",
            "tasklist", "tasklist /", "driverquery", "getmac", "vol", "chkdsk",
            "powercfg /getactivescheme", "powercfg /list",
            "w32tm /query", "fsutil fsinfo", "reg query", "reg export",
            # 开发工具
            "python --version", "python -V", "pip list", "pip show", "node -v",
            "npm -v", "git status", "git log", "git diff", "git branch",
            "git remote", "git show", "git rev-parse", "git config --get",
            "docker ps", "docker images", "docker version",
            "ollama list", "ollama ps", "ollama show",
            "nvidia-smi", "nvcc --version",
            # 其他
            "echo", "cls", "color", "title", "typeperf", "systeminfo",
        ],
    },
    "search": {
        "enabled": True,
        "max_results": 5,
        "timeout_s": 10,
        "region": "cn-zh",
    },
    "memory": {
        "enabled": True,
        "max_inject": 6,
    },
    "device": {
        # 旧后端的设备控制接口（有就接，没有就本地模拟）
        "backend_url": "http://127.0.0.1:8000",
        "token": "",
        "simulate": True,
    },
    "phone": {
        # 手机 Agent（方案2：Tailscale 内网 HTTP）
        "agent_url": "http://100.115.152.111:9100",
        "token": "",
        "enabled": True,
    },
    "log": {
        "level": "INFO",
        "file": "logs/pccore.log",
        "max_bytes": 5_000_000,
        "backup_count": 3,
    },
}


def ensure_dirs() -> None:
    """启动时确保所有目录存在。"""
    for d in (CONFIG_DIR, DATA_DIR, LOGS_DIR, WORKSPACE):
        d.mkdir(parents=True, exist_ok=True)
