"""`/api/app`：手机 App 的版本查询与 APK 下载（自更新用）。

手机端流程：
  1. GET /api/app/version  → 比 versionCode
  2. 新版就 GET /api/app/download → 存到 cache → 拉起安装器
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ..auth import require_auth

logger = logging.getLogger("pccore.api.app")

router = APIRouter(prefix="/api/app", tags=["app"], dependencies=[Depends(require_auth)])

# APK 与版本信息放这里
APP_DIR = Path(r"E:\WH\firmware\phone-app")
APK_FILE = APP_DIR / "xiaoban.apk"
MANIFEST = APP_DIR / "AndroidManifest.xml"


def _read_version() -> tuple[int, str]:
    """从 AndroidManifest.xml 里抠 versionCode / versionName。"""
    code, name = 0, "0.0.0"
    try:
        text = MANIFEST.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'android:versionCode="(\d+)"', text)
        if m:
            code = int(m.group(1))
        m = re.search(r'android:versionName="([^"]+)"', text)
        if m:
            name = m.group(1)
    except Exception:  # noqa: BLE001
        logger.warning("读版本号失败", exc_info=True)
    return code, name


@router.get("/version")
async def version():
    code, name = _read_version()
    apk_ok = APK_FILE.exists()
    notes_file = APP_DIR / "CHANGELOG.md"
    notes = ""
    if notes_file.exists():
        try:
            notes = notes_file.read_text(encoding="utf-8")[:800]
        except Exception:  # noqa: BLE001
            pass
    return {
        "ok": True,
        "versionCode": code,
        "versionName": name,
        "size": APK_FILE.stat().st_size if apk_ok else 0,
        "available": apk_ok,
        "notes": notes,
    }


@router.get("/download")
async def download():
    if not APK_FILE.exists():
        return {"ok": False, "error": "服务器上还没有 APK"}
    return FileResponse(
        str(APK_FILE),
        media_type="application/vnd.android.package-archive",
        filename="xiaoban.apk",
    )
