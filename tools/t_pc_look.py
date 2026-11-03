"""pc.look：截图并「看懂」画面内容。

小伴的需求：「截图后希望能直接看到画面内容，现在只能拿到文件路径，看不到图」

做法：截屏 → 转 base64 → 交给支持视觉的模型 → 返回文字描述。
所以模型不需要原生多模态能力，也能"看见"。
"""

from __future__ import annotations

import base64
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from . import _common as C
from . import _desktop_common as D


def _cfg(ctx: Any) -> dict:
    try:
        from core import config as cfg_mod  # noqa: PLC0415

        return cfg_mod.load()
    except Exception:  # noqa: BLE001
        return {}


def _vision_model(cfg: dict) -> tuple[str, str, str]:
    """返回 (base_url, api_key, model)。优先用专门的视觉模型配置。"""
    brain = cfg.get("brain") or {}
    providers = cfg.get("providers") or {}

    # 1) 显式配了 vision 就用
    vis = cfg.get("vision") or {}
    if vis.get("model"):
        pname = vis.get("provider") or brain.get("provider") or "gateway"
        conf = providers.get(pname) or providers.get("gateway") or {}
        return (str(conf.get("base_url") or "").rstrip("/"),
                str(conf.get("api_key") or ""),
                str(vis.get("model")))

    # 2) 否则用当前 provider 的模型
    pname = brain.get("provider") or "gateway"
    conf = providers.get(pname) or providers.get("gateway") or {}
    return (str(conf.get("base_url") or "").rstrip("/"),
            str(conf.get("api_key") or ""),
            str(brain.get("model") or "deepseek/deepseek-flash"))


def run(args: dict, ctx: Any) -> dict:
    # 1) 拿图：给了 path 就用，没给就现截一张
    path = str(args.get("path") or "").strip()
    tmp_shot = ""
    if not path:
        ws = Path(getattr(ctx, "workspace", None) or ".")
        ws.mkdir(parents=True, exist_ok=True)
        p = ws / f"look_{int(time.time())}.png"
        try:
            w, h = D.screenshot(str(p))
        except Exception as exc:  # noqa: BLE001
            return C.fail(f"截图失败：{exc}", f"{type(exc).__name__}")
        path = str(p)
        tmp_shot = str(p)
    else:
        try:
            p = C.resolve_path(path, ctx)
        except ValueError:
            return C.fail(f"路径不对：{path}", "BadPath")
        if not p.exists():
            return C.fail(f"没有这个图片：{p}", "NotFound")
        path = str(p)

    # 2) 读图 → base64
    try:
        raw = Path(path).read_bytes()
    except Exception as exc:  # noqa: BLE001
        return C.fail(f"读图失败：{exc}", "ReadFailed")

    if len(raw) > 8 * 1024 * 1024:
        return C.fail("图片太大（>8MB），先缩小再让我看。", "TooLarge")

    b64 = base64.b64encode(raw).decode("ascii")

    # 3) 问视觉模型
    cfg = _cfg(ctx)
    base_url, api_key, model = _vision_model(cfg)
    if not base_url:
        return C.fail("没配推理服务地址，看不了图。", "NoProvider")

    question = str(args.get("question") or "这张屏幕上是什么？把界面上的关键文字、按钮、以及当前在做什么，用中文简要描述。")
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        "max_tokens": 600,
        "stream": False,
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(base_url + "/chat/completions",
                                     data=json.dumps(body).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    except Exception as exc:  # noqa: BLE001
        return C.fail(
            f"看图失败（{type(exc).__name__}）。可能是模型不支持图片输入，"
            f"可以在 config.json 里配 vision.model 指定一个视觉模型。",
            f"{type(exc).__name__}: {exc}",
        )

    text = (text or "").strip()
    if not text:
        return C.fail("模型没返回内容（可能这个模型不支持看图）。", "EmptyVision")

    return C.ok(text, path=path, model=model, screenshot=tmp_shot)


TOOL = {
    "name": "pc.look",
    "title": "看屏幕内容",
    "desc": "截一张屏（或看指定图片），直接告诉你画面上有什么。想知道界面上写了什么、按钮在哪、操作成功没有时用，比只要文件路径有用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "想问这张图什么（可省略）"},
            "path": {"type": "string", "description": "指定图片路径；省略则现截一张屏"},
        },
    },
    "run": C.guard(run),
}
