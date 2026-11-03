"""让「主动说话」真的是小伴自己说的，而不是后台写死的通知文案。

用户原话：「给他真正的会话功能，而不是你在后台给他说他需要主动说话」

做法：autopilot 触发时，把「触发原因 + 当前上下文」交给模型，
让它用自己的语气生成一句话。模型挂了就退回原始文案，不阻塞。
"""

from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger("pccore.proactivegen")


def _provider() -> tuple[str, str, str]:
    try:
        from . import config as cfg_mod  # noqa: PLC0415

        cfg = cfg_mod.load()
        brain = cfg.get("brain") or {}
        pname = brain.get("provider") or "gateway"
        conf = (cfg.get("providers") or {}).get(pname) or {}
        return (
            str(conf.get("base_url") or "").rstrip("/"),
            str(conf.get("api_key") or ""),
            str(brain.get("model") or "deepseek/deepseek-flash"),
        )
    except Exception:  # noqa: BLE001
        return "", "", ""


def _context_block() -> str:
    """给模型一点上下文：现在几点、用户在干什么、最近聊了什么。"""
    parts = []
    try:
        import time as _t  # noqa: PLC0415

        parts.append("现在时间：" + _t.strftime("%Y-%m-%d %H:%M %A"))
    except Exception:  # noqa: BLE001
        pass
    try:
        from tools import _desktop_common as D  # noqa: PLC0415

        fg = D.foreground_title()
        if fg:
            parts.append(f"用户当前窗口：{fg}")
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import grand_log  # noqa: PLC0415

        recent = grand_log.state_snippet()
        if recent:
            parts.append("最近发生的事：\n" + recent[-500:])
    except Exception:  # noqa: BLE001
        pass
    # 记住的用户信息（怎么称呼他、他的偏好），让主动说话不叫错人
    try:
        from . import memory_engine  # noqa: PLC0415

        memory_engine.init()
        mems = memory_engine.recall_long_term("", limit=6)
        if mems:
            parts.append("你记得的关于他的事：\n" +
                         "\n".join("- " + str(m.get("content") or "")[:60] for m in mems))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(parts)


def generate(reason: str, kind: str = "reminder") -> str:
    """让模型把「触发原因」说成一句人话。失败就返回原始 reason。"""
    base_url, api_key, model = _provider()
    if not base_url:
        return reason

    persona = ""
    try:
        from . import persona  # noqa: PLC0415

        persona = persona.base_prompt()
    except Exception:  # noqa: BLE001
        persona = "你是「小伴」，住在用户电脑里的伙伴。说话口语、短句，一次一两句。"

    tone = {
        "reminder": "现在有个提醒，你要主动跟用户说一句",
        "alert": "发现一个需要用户注意的情况，你要主动说一句",
        "greeting": "你想跟用户打个招呼",
        "recall": "你想起以前的事，想主动提一句",
    }.get(kind, "你要主动跟用户说一句")

    prompt = (
        f"{persona}\n\n"
        f"【现在的情况】\n{tone}。\n"
        f"触发原因：{reason}\n\n"
        f"{_context_block()}\n\n"
        f"【要求】\n"
        f"- 直接说你要说的话，不要解释你在干什么\n"
        f"- 不要用「提醒您」「请注意」这种系统播报腔\n"
        f"- 不超过 40 个字，一两句话\n"
        f"- 如果觉得这会儿不该打扰，就只回一个词：SKIP"
    )

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200,
        "temperature": 0.9,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(base_url + "/chat/completions",
                                     data=json.dumps(body).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        text = text.strip().strip('"').strip()
        if not text or text.upper().startswith("SKIP"):
            return ""
        return text[:200]
    except Exception:  # noqa: BLE001
        logger.debug("生成主动消息失败，用原始文案", exc_info=True)
        return reason
