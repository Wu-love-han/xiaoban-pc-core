"""pc.ui：枚举 Windows 界面元素（文字 + 坐标 + 类型）。

为什么需要：
  pc.look 只能返回文字描述，模型不知道"输入框在 (1300,1200)"这种精确坐标，
  只能猜——猜错了就点不到，字也打不进去（实测踩过，AI 卡了十几轮）。

  这个工具用 Windows UIAutomation 拿到真正的元素树，
  每个元素带名字和矩形，模型可以直接按名字找、按坐标点。
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from . import _common as C

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_PS = r'''
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
} catch {
  Write-Output '{"ok":false,"error":"加载 UIAutomation 失败"}'
  exit
}

function Walk($el, $depth, $max, $list) {
  if ($el -eq $null -or $depth -gt 18 -or $list.Count -ge $max) { return }
  try {
    $n = $el.Current.Name
    $ct = $el.Current.ControlType.ProgrammaticName
    $r = $el.Current.BoundingRectangle
    $w = [int]$r.Width
    $h = [int]$r.Height
    $interactive = $false
    try {
      $interactive = $el.Current.IsKeyboardFocusable -or ($el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern) -ne $null)
    } catch { }
    if (($n -ne '' -or $interactive) -and $w -gt 0 -and $h -gt 0) {
      $ctShort = $ct -replace '^ControlType\.', ''
      $null = $list.Add([pscustomobject]@{
        name = $n
        type = $ctShort
        x = [int]($r.X + $r.Width / 2)
        y = [int]($r.Y + $r.Height / 2)
        w = $w
        h = $h
        interactive = $interactive
      })
    }
  } catch { }
  try {
    $child = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetFirstChild($el)
    while ($child -ne $null) {
      Walk $child ($depth + 1) $max $list
      $child = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetNextSibling($child)
    }
  } catch { }
}

$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]__HWND__)
if ($root -eq $null) { Write-Output '{"ok":false,"error":"拿不到窗口"}'; exit }
$list = New-Object System.Collections.ArrayList
Walk $root 0 __MAX__ $list
$out = [pscustomobject]@{ ok = $true; count = $list.Count; elements = $list }
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Output ($out | ConvertTo-Json -Depth 4 -Compress)
'''


def _run_ps(hwnd: int, max_elems: int) -> tuple[bool, Any]:
    script = _PS.replace("__HWND__", str(hwnd)).replace("__MAX__", str(max_elems))
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=40, creationflags=_CREATE_NO_WINDOW,
        )
        raw = r.stdout or b""
        # PowerShell 可能输出 GBK，先试 UTF-8 再试 GBK
        for enc in ("utf-8", "gbk"):
            try:
                out = raw.decode(enc).strip()
                break
            except UnicodeDecodeError:
                continue
        else:
            out = raw.decode("utf-8", "replace").strip()
        # 只取最后一行 JSON（前面可能有杂音）
        if out and not out.startswith("{"):
            lines = [ln for ln in out.splitlines() if ln.strip().startswith("{")]
            out = lines[-1] if lines else out
        if not out:
            err = (r.stderr or b"").decode("gbk", "replace")[:200]
            return False, err or "没有输出"
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out[:300] if out else "返回不是 JSON"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def run(args: dict, ctx: Any) -> dict:
    from tools import _desktop_common as D  # noqa: PLC0415

    kw = str(args.get("window") or "").strip()
    if kw:
        w = D.find_window(kw)
        if not w:
            names = "、".join(x["title"][:20] for x in D.list_windows()[:6])
            return C.fail(f"没找到标题含「{kw}」的窗口。现在开着：{names}", "NotFound")
        D.focus_window(w["hwnd"])
        hwnd = w["hwnd"]
        title = w["title"]
    else:
        hwnd = D.foreground_hwnd()
        title = D.foreground_title()
        if not hwnd:
            return C.fail("拿不到当前窗口", "NoWindow")

    try:
        limit = int(args.get("limit") or 60)
    except (TypeError, ValueError):
        limit = 60
    limit = max(5, min(200, limit))

    ok, data = _run_ps(hwnd, limit)
    if not ok:
        return C.fail(f"读界面元素失败：{data}", "UIFailed")
    if not data.get("ok"):
        return C.fail(data.get("error") or "读失败", "UIFailed")

    elems = data.get("elements") or []
    # 过滤：只留有名字或可交互的
    if bool(args.get("interactive_only")):
        elems = [e for e in elems if e.get("interactive")]

    lines = []
    for i, e in enumerate(elems[:limit]):
        name = (e.get("name") or "")[:40]
        tag = "可交互" if e.get("interactive") else ""
        lines.append(f"{i}. [{e.get('type')}] {name} @({e.get('x')},{e.get('y')}) {tag}")

    return C.ok(
        f"窗口「{title}」里有 {len(elems)} 个元素：\n" + "\n".join(lines),
        window=title, hwnd=hwnd, count=len(elems), elements=elems[:limit],
    )


TOOL = {
    "name": "pc.ui",
    "title": "看界面元素（带坐标）",
    "desc": (
        "列出窗口里所有界面元素的名字、类型和精确坐标。"
        "要点击某个按钮/输入框时先调这个，拿到坐标再 pc.click，比靠截图猜坐标准得多。"
        "window 参数可以指定窗口标题里的字。"
    ),
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "window": {"type": "string", "description": "窗口标题里的几个字（省略=当前前台窗口）"},
            "limit": {"type": "integer", "description": "最多几个元素（默认 60）"},
            "interactive_only": {"type": "boolean", "description": "只看可交互的（按钮/输入框）"},
        },
    },
    "run": C.guard(run),
}
