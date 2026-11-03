"""「身体状态」——让模型知道自己现在到底能做什么。

为什么需要：用户问「你知道你多了哪些能力吗」，模型只会数工具个数，
不知道自己有手机无障碍、能自更新、能同时操作两台设备。
这份描述每轮动态生成，能力变了模型立刻知道。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("pccore.body")


def _phone_state() -> str:
    """手机端现在是什么状态。"""
    try:
        from tools import _adb_common as A  # noqa: PLC0415

        if A.app_ready():
            info = A.app_shell_info() if hasattr(A, "app_shell_info") else {}
            level = info.get("level", "")
            shell_note = ""
            if level == "shizuku":
                shell_note = (" **还有 shell 权限**（借 Shizuku，uid=2000，不需要 root）："
                              "phone.shell 能装应用、改系统设置、读系统信息、dumpsys。")
            elif level:
                shell_note = " 但 Shizuku 没连上，暂时没有系统级权限。"
            return ("手机端：**已连上，走无障碍服务**（读界面约 0.3 秒、点按钮约 0.3 秒、"
                    "中文输入约 0.7 秒，比截图快 8 倍）。可以用 phone.ui_tree 看界面、"
                    "phone.click_text 按文字点、phone.input_text 打中文。" + shell_note)
        if A.app_available():
            return ("手机端：App 连着，但**无障碍服务没开**——现在只能走 ADB 慢通道"
                    "（读界面 2.3 秒，不能打中文）。可以提醒用户去系统设置打开「小伴 · 界面操作」。")
        ok, _ = A.device_ready()
        if ok:
            return "手机端：只有 ADB（USB）通道，App 能力服务没连上。"
        return "手机端：现在没连上（USB 没插 / App 没开 / 网络不通）。"
    except Exception:  # noqa: BLE001
        logger.debug("读手机状态失败", exc_info=True)
        return ""


def _pc_state() -> str:
    """电脑端桌面控制能力。"""
    try:
        from tools import _desktop_common as D  # noqa: PLC0415

        w, h = D.screen_size()
        fg = D.foreground_title()
        extra = f"，当前前台是「{fg}」" if fg else ""
        return (f"电脑端：**能操作真实鼠标键盘**（屏幕 {w}x{h}{extra}）。"
                "用 pc.screen 截图、**pc.look 直接看懂画面内容**、pc.click 点坐标、"
                "pc.type 往窗口打字、pc.hotkey 按快捷键、pc.windows 看开了哪些窗口、"
                "pc.context 看用户在干什么。"
                "另外 **pc.self_update 能读改你自己的代码和配置**（带备份+语法校验+自动回滚）。")
    except Exception:  # noqa: BLE001
        return ""


def _update_state() -> str:
    """自更新能力。"""
    try:
        from . import config as cfg_mod  # noqa: PLC0415

        cfg = cfg_mod.load()
        has_app_api = True
        if not has_app_api:
            return ""
        return ("自更新：**手机 App 支持自更新**。PC 上 `/api/app/version` 报最新版本号，"
                "App 启动时会自动比对并下载安装。所以「你能不能更新自己」的答案是："
                "能——只要把新版 APK 放到 PC 上并升版本号，手机 App 下次启动就会自己升级。")
    except Exception:  # noqa: BLE001
        return ""


def _sync_state() -> str:
    """三端同步状态。"""
    try:
        from . import sync_hub  # noqa: PLC0415

        st = sync_hub.state()
        terms = sync_hub.list_terminals()
        names = "、".join(
            f"{t.get('name') or t.get('id')}{'（在线）' if t.get('online') else '（离线）'}"
            for t in terms
        )
        if not names:
            return ""
        return (f"三端：{names}。你可以用 sync 相关接口在终端之间下指令、同步日志和记忆；"
                "手机 App 也能反过来调 PC 的工具（手机 AI 操控电脑）。")
    except Exception:  # noqa: BLE001
        return ""


def describe() -> str:
    """拼一段「你现在的身体」描述；全拿不到就返回空串（不污染提示词）。"""
    parts = [_pc_state(), _phone_state(), _update_state(), _sync_state()]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return "\n".join(f"- {p}" for p in parts)
