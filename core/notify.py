"""系统通知——小伴要说话、要你确认的时候，弹 Windows 通知。

为什么需要（用户原话）：「最好加一个通知，方便我在其他软件上也能看到消息」

实现：PowerShell + WinRT 的 ToastNotification，Win10/11 原生支持。
失败就退化成控制台响铃，绝不影响主流程。
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

logger = logging.getLogger("pccore.notify")

_last: dict[str, float] = {}
_lock = threading.Lock()

# 同类通知的冷却，防止刷屏
COOLDOWN_S = 30

_PS_TEMPLATE = r'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] | Out-Null
$xml = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{title}</text>
      <text>{body}</text>
    </binding>
  </visual>
  <audio src="ms-winsoundevent:Notification.Default"/>
</toast>
"@
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$toast = New-Object Windows.UI.Notifications.ToastNotification $doc
$app = "{appid}"
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
'''


def _xml_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def toast(title: str, body: str, key: str = "", appid: str = "小伴") -> bool:
    """弹一条 Windows 通知。key 用于同类冷却。"""
    k = key or title
    now = time.time()
    with _lock:
        if now - _last.get(k, 0.0) < COOLDOWN_S:
            return False
        _last[k] = now

    script = _PS_TEMPLATE.format(
        title=_xml_escape(title[:80]),
        body=_xml_escape(body[:200]),
        appid=_xml_escape(appid),
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
            capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:  # noqa: BLE001
        logger.debug("弹通知失败", exc_info=True)
        return False


def toast_async(title: str, body: str, key: str = "") -> None:
    """不阻塞主流程的通知。"""
    t = threading.Thread(target=toast, args=(title, body, key), daemon=True)
    t.start()


# ---------------------------------------------------------------- 与业务挂钩

def notify_proactive(text: str, kind: str = "note") -> None:
    """主动消息 → 系统通知。"""
    title = {"reminder": "小伴提醒", "alert": "小伴 · 需要你处理", "notice": "小伴"}.get(kind, "小伴")
    toast_async(title, text, key="proactive")


def notify_consent(target: str, detail: str = "") -> None:
    """有底线操作等你确认 → 系统通知（这个必须弹，不能漏）。"""
    toast_async(
        "小伴要改底线文件，等你确认",
        f"{target}\n{detail[:120]}\n\n去本机后台看板点同意或拒绝",
        key="consent:" + target,
    )


def notify_done(what: str) -> None:
    """任务完成提醒。"""
    toast_async("小伴做完了", what, key="done")
