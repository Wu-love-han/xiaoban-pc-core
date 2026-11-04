"""phone.vdisplay：在虚拟屏上操作手机（不占用户真实屏幕）。

用户需求：「手机端在操作的时候在后台，不要影响我玩手机」

原理：
  手机 App 通过 Shizuku 起一个 UserService（shell 身份），在里面创建
  VirtualDisplay，然后用隐藏 API 把触摸事件注入到那个虚拟屏。
  真实屏幕完全不受影响。

前提：
  - 手机 App v2.5.0+
  - Shizuku 授权
  - 部分 ROM 不支持（创建会返回 -1）
"""

from __future__ import annotations

from typing import Any

from . import _common as C
from . import _adb_common as A


def _call(path: str, payload: dict | None = None, timeout: int = 30) -> tuple[bool, dict]:
    ok, data = A._app_request(path, method="POST" if payload is not None else "GET",
                              body=payload, timeout=timeout)
    if not ok:
        return False, {"error": str(data.get("error") or "连不上手机 App")}
    return True, data


def run(args: dict, ctx: Any) -> dict:
    action = str(args.get("action") or "info").strip().lower()

    if action == "info":
        ok, d = _call("/vdisplay/info")
        if not ok:
            return C.fail(d.get("error", ""), "Unreachable")
        if not d.get("ok"):
            return C.fail(d.get("error") or "虚拟屏服务不可用", "NotAvailable")
        did = d.get("displayId", -1)
        if did is None or did < 0:
            return C.ok(
                "虚拟屏服务在，但还没创建屏幕。用 action=create 建一个。\n"
                f"  uid={d.get('uid')} 输入注入={'就绪' if d.get('inputReady') else '不可用'}",
                info=d,
            )
        return C.ok(
            f"虚拟屏 #{did}  {d.get('width')}x{d.get('height')} @{d.get('dpi')}dpi\n"
            f"  已渲染 {d.get('frames')} 帧 · 输入注入{'就绪' if d.get('inputReady') else '不可用'}",
            info=d,
        )

    if action == "create":
        w = int(args.get("width") or 720)
        h = int(args.get("height") or 1600)
        dpi = int(args.get("dpi") or 320)
        ok, d = _call("/vdisplay/create", {"width": w, "height": h, "dpi": dpi}, timeout=60)
        if not ok:
            return C.fail(d.get("error", ""), "Unreachable")
        if not d.get("ok"):
            return C.fail(
                d.get("error") or "创建失败",
                "CreateFailed",
            )
        return C.ok(
            f"虚拟屏建好了：#{d.get('displayId')}  {w}x{h} @{dpi}dpi\n"
            "现在可以用 launch 在上面开应用，tap/swipe/type 操作，真实屏幕不受影响。",
            display_id=d.get("displayId"),
        )

    if action == "release":
        ok, d = _call("/vdisplay/release", {})
        return C.ok("虚拟屏已释放") if (ok and d.get("ok")) else C.fail("释放失败", "Failed")

    if action == "launch":
        pkg = str(args.get("package") or "").strip()
        if not pkg:
            return C.fail("要给 package", "MissingArg")
        ok, d = _call("/vdisplay/launch", {"package": pkg}, timeout=40)
        if not ok or not d.get("ok"):
            return C.fail(f"在虚拟屏上启动 {pkg} 失败", "LaunchFailed")
        return C.ok(f"已在虚拟屏上启动 {pkg}（你的屏幕没动）", package=pkg)

    if action == "tap":
        ok, d = _call("/vdisplay/tap", {"x": int(args.get("x", 0)), "y": int(args.get("y", 0))})
        return C.ok(f"虚拟屏点击 ({args.get('x')},{args.get('y')})") if (ok and d.get("ok")) else C.fail("点击失败", "Failed")

    if action == "swipe":
        ok, d = _call("/vdisplay/swipe", {
            "x1": int(args.get("x1", 0)), "y1": int(args.get("y1", 0)),
            "x2": int(args.get("x2", 0)), "y2": int(args.get("y2", 0)),
            "ms": int(args.get("ms") or 300),
        })
        return C.ok("虚拟屏滑动完成") if (ok and d.get("ok")) else C.fail("滑动失败", "Failed")

    if action == "key":
        ok, d = _call("/vdisplay/key", {"keycode": int(args.get("keycode", 4))})
        return C.ok(f"虚拟屏按键 {args.get('keycode')}") if (ok and d.get("ok")) else C.fail("按键失败", "Failed")

    if action == "type":
        ok, d = _call("/vdisplay/type", {"text": str(args.get("text") or "")})
        return C.ok("虚拟屏输入完成") if (ok and d.get("ok")) else C.fail("输入失败", "Failed")

    if action == "screenshot":
        ok, d = _call("/vdisplay/screenshot", None, timeout=40)
        if not ok:
            return C.fail(d.get("error", ""), "Unreachable")
        if not d.get("ok"):
            return C.fail(d.get("error") or "截不到图", "NoFrame")
        return C.ok(
            f"虚拟屏截图 {d.get('size')} 字节（base64 已省略，需要的话用 data 取）",
            size=d.get("size"),
            base64=d.get("base64"),
        )

    return C.fail(f"不认识的 action：{action}", "BadAction")


TOOL = {
    "name": "phone.vdisplay",
    "title": "虚拟屏操作（不占真实屏幕）",
    "desc": (
        "在手机的虚拟屏幕上跑应用、点击、打字——真实屏幕完全不受影响，用户可以继续用手机。"
        "流程：create 建屏 → launch 开应用 → tap/type 操作 → screenshot 看效果 → release 释放。"
        "需要手机 App v2.5.0+ 和 Shizuku 授权。部分手机不支持。"
    ),
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["info", "create", "release", "launch", "tap", "swipe", "key", "type", "screenshot"],
                "description": "info=看状态，create=建屏，launch=开应用，tap/swipe/key/type=操作，screenshot=截图，release=释放",
            },
            "width": {"type": "integer", "description": "虚拟屏宽（默认 720）"},
            "height": {"type": "integer", "description": "虚拟屏高（默认 1600）"},
            "dpi": {"type": "integer", "description": "DPI（默认 320）"},
            "package": {"type": "string", "description": "要启动的包名"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "x1": {"type": "integer"},
            "y1": {"type": "integer"},
            "x2": {"type": "integer"},
            "y2": {"type": "integer"},
            "ms": {"type": "integer", "description": "滑动时长毫秒"},
            "keycode": {"type": "integer", "description": "键码，4=返回 3=Home"},
            "text": {"type": "string", "description": "要输入的文字"},
        },
        "required": ["action"],
    },
    "run": C.guard(run),
}
