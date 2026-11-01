"""大脑：一轮对话的完整生命周期。

**这是整个重做的核心。** 旧的 task_agent 用一次模型调用判 task/chat，
判成 task 就切模式，人格消失。这里不再有那个东西。

新的做法只有一条链：
    persona(system) → provider 流式 → 有 tool_calls 就执行 → 回灌 → 再让模型说话

「是不是指令」不再是一个判断，而是**模型有没有调工具**这个事实本身。
所以聊天和做事永远是同一个人、同一个语气。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import AsyncIterator

from . import config as cfg_mod
from . import db, persona
from .paths import WORKSPACE
from .providers import ProviderEvent, get_provider, parse_args
from .toolbase import ToolContext, registry

logger = logging.getLogger("pccore.brain")

# 每个会话一个取消标志：用户点「停止」时置位，循环里检查
_aborts: dict[str, asyncio.Event] = {}

# 等待人工确认的槽位：approval_id -> Future[bool]
_pending_approvals: dict[str, asyncio.Future] = {}

# 兜底话术（只在模型真的什么都没说的时候用）
FALLBACK_EMPTY = "嗯…我这会儿有点卡，你再说一遍？"
FALLBACK_MAX_ROUNDS = "这个我绕进去了，先停一下，咱们换个说法试试。"


# ---------------------------------------------------------------- 取消

def request_abort(session_id: str) -> None:
    ev = _aborts.get(session_id)
    if ev is not None:
        ev.set()
        logger.info("会话 %s 请求中止", session_id)


def _abort_event(session_id: str) -> asyncio.Event:
    ev = _aborts.get(session_id)
    if ev is None:
        ev = asyncio.Event()
        _aborts[session_id] = ev
    return ev


def _clear_abort(session_id: str) -> None:
    _aborts.pop(session_id, None)


# ---------------------------------------------------------------- 审批

def resolve_approval(approval_id: str, approved: bool) -> bool:
    """由 server 的 /api/approvals/{id} 调用，唤醒等待中的大脑。"""
    fut = _pending_approvals.get(approval_id)
    if fut is None or fut.done():
        return False
    fut.set_result(bool(approved))
    return True


async def _wait_approval(approval_id: str, timeout_s: float) -> str:
    """等人工决定。返回 approved / denied / expired。"""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    _pending_approvals[approval_id] = fut
    try:
        approved = await asyncio.wait_for(fut, timeout=timeout_s)
        return "approved" if approved else "denied"
    except asyncio.TimeoutError:
        return "expired"
    finally:
        _pending_approvals.pop(approval_id, None)


# ---------------------------------------------------------------- 辅助

def _memory_block(session_id: str, text: str) -> str:
    """记忆注入块。失败绝不影响主流程。"""
    try:
        cfg = cfg_mod.load()
        if not (cfg.get("memory") or {}).get("enabled", True):
            return ""
        limit = int((cfg.get("memory") or {}).get("max_inject") or 6)
        items = db.recall(text, scope=session_id, limit=limit)
        if not items:
            return ""
        lines = [f"- {it['key']}：{it['value']}" for it in items]
        return "\n".join(lines)
    except Exception:  # noqa: BLE001
        logger.warning("记忆注入失败，忽略", exc_info=True)
        return ""


def _build_messages(session_id: str, user_text: str) -> list[dict]:
    cfg = cfg_mod.load()
    brain_cfg = cfg.get("brain") or {}
    turns = int(brain_cfg.get("history_turns") or 8)

    system = persona.build_system_prompt(
        tool_catalog=registry.catalog_for_prompt(),
        memory_block=_memory_block(session_id, user_text),
    )
    msgs: list[dict] = [{"role": "system", "content": system}]
    msgs.extend(db.history_for_model(session_id, turns=turns))
    msgs.append({"role": "user", "content": user_text})
    return msgs


def _approval_say(name: str, args: dict) -> str:
    """危险动作要用人格开口问。这里给的是"她说的话"，不是系统弹窗文案。

    尽量具体（带上路径/命令），否则用户没法判断。
    """
    spec = registry.get(name)
    title = spec.title if spec else name
    if name == "pc.delete":
        target = args.get("path") or args.get("target") or "那个东西"
        return f"删之前问一句——{target}，真删啊？删了找不回来。"
    if name == "pc.write_file":
        target = args.get("path") or "那个文件"
        return f"要往 {target} 里写东西，会盖掉原来的内容。写吗？"
    if name == "pc.shell":
        cmd = args.get("command") or "那条命令"
        return f"要跑一下命令：{cmd}。你确认我就跑。"
    return f"要{title}，你点头我就动手。"


def _result_for_model(res: dict) -> dict:
    """工具结果回灌给模型时的形状：只给必要的，省 token。"""
    return {
        "ok": bool(res.get("ok")),
        "output": str(res.get("output") or ""),
    }


# ---------------------------------------------------------------- 主循环

async def run_turn(
    session_id: str,
    text: str,
    model: str | None = None,
    reasoning: str | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    """跑一轮。yield (事件名, payload)，事件名严格按契约第四节。"""
    cfg = cfg_mod.load()
    bcfg = cfg.get("brain") or {}
    model = (model or bcfg.get("model") or "deepseek/deepseek-flash").strip()
    reasoning = (reasoning if reasoning is not None else bcfg.get("reasoning") or "none").strip()
    max_rounds = int(bcfg.get("max_rounds") or 6)
    approval_timeout = float(bcfg.get("approval_timeout_s") or 300)
    temperature = float(bcfg.get("temperature") or 0.8)
    top_p = float(bcfg.get("top_p") or 0.92)
    max_tokens = int(bcfg.get("max_tokens") or 1200)

    abort = _abort_event(session_id)
    abort.clear()

    t_start = time.perf_counter()
    tool_count = 0
    usage = {"in": 0, "out": 0}
    all_tool_calls: list[dict] = []
    content_parts: list[str] = []
    thinking_parts: list[str] = []

    # 落用户消息（brain 负责，server 不重复落）
    db.add_message(session_id, "user", text)
    sess = db.get_session(session_id)
    if sess and not (sess.get("title") or "").strip():
        db.touch_session(session_id, title=text[:24])

    messages = _build_messages(session_id, text)
    tools = registry.schemas()

    provider_name = bcfg.get("provider") or "gateway"
    provider = get_provider(provider_name)

    degraded = ""
    round_no = 0
    finished = False

    while round_no < max_rounds:
        round_no += 1
        if abort.is_set():
            break

        round_content: list[str] = []
        round_thinking: list[str] = []
        calls: list[ProviderEvent] = []
        got_error = ""
        got_any = False

        try:
            async for ev in provider.stream(
                messages,
                tools,
                model=model,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                reasoning=reasoning,
            ):
                got_any = True
                if ev.kind == "thinking":
                    round_thinking.append(ev.text)
                    yield ("thinking", {"text": ev.text})
                elif ev.kind == "content":
                    round_content.append(ev.text)
                    yield ("content", {"text": ev.text})
                elif ev.kind == "tool_call":
                    calls.append(ev)
                elif ev.kind == "done":
                    usage["in"] += int((ev.usage or {}).get("in") or 0)
                    usage["out"] += int((ev.usage or {}).get("out") or 0)
                elif ev.kind == "error":
                    got_error = ev.text or "推理出错"
                    break
                if abort.is_set():
                    break
        except Exception as exc:  # noqa: BLE001
            logger.exception("provider 流异常")
            got_error = f"{type(exc).__name__}: {exc}"

        # ---- 主 provider 失败 → 尝试兜底一次（整轮只降级一次）
        if got_error and not degraded:
            fb_name = bcfg.get("fallback_provider") or "ollama"
            fb_model = bcfg.get("fallback_model") or "qwen2.5:7b"
            logger.warning("主推理失败（%s），尝试回落 %s/%s", got_error, fb_name, fb_model)
            try:
                fb = get_provider(fb_name)
                degraded = f"{fb_name}/{fb_model}"
                provider = fb
                model = fb_model
                round_no -= 1  # 这一轮不算数
                continue
            except Exception:  # noqa: BLE001
                pass

        if got_error:
            yield ("error", {"message": got_error})
            db.add_event("error", {"message": got_error, "model": model}, session_id)
            finished = True
            break

        if not got_any:
            yield ("error", {"message": "推理服务没有任何返回"})
            finished = True
            break

        content_parts.extend(round_content)
        thinking_parts.extend(round_thinking)

        # ---- 没有工具调用：这就是「聊天」，本轮结束
        if not calls:
            finished = True
            break

        # ---- 有工具调用：这就是「指令」，执行后回灌，让模型继续说
        # 先把这一轮的 assistant 消息（含 tool_calls）塞进上下文
        messages.append(
            {
                "role": "assistant",
                "content": "".join(round_content),
                "tool_calls": [
                    {
                        "id": c.call_id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments or "{}"},
                    }
                    for c in calls
                ],
            }
        )

        for c in calls:
            tool_count += 1
            # provider 发出去的是线上名（pc_list_dir），模型回来的也是线上名；
            # 内部一律用规范名（pc.list_dir）。这里做一次归一。
            canon = registry.to_canon(c.name)
            if canon != c.name:
                c = ProviderEvent(
                    kind="tool_call",
                    call_id=c.call_id,
                    name=canon,
                    arguments=c.arguments,
                )
            spec = registry.get(c.name)
            args, arg_err = parse_args(c.arguments)
            all_tool_calls.append(
                {"call_id": c.call_id, "name": c.name, "args": args, "error": arg_err}
            )
            yield (
                "tool_call",
                {
                    "call_id": c.call_id,
                    "name": c.name,
                    "title": (spec.title if spec else c.name),
                    "args": args,
                },
            )

            if spec is None:
                res = {"ok": False, "output": f"没有这个工具：{c.name}", "ms": 0}
            elif arg_err:
                res = {"ok": False, "output": f"参数不对：{arg_err}", "ms": 0}
            else:
                ctx = ToolContext(
                    session_id=session_id,
                    call_id=c.call_id,
                    workspace=Path(WORKSPACE),
                    config=cfg,
                )

                # ---- 危险动作：先问人，不静默执行
                if spec.danger:
                    ap = db.create_approval(session_id, c.call_id, c.name, args)
                    say = _approval_say(c.name, args)
                    yield (
                        "approval",
                        {
                            "approval_id": ap["id"],
                            "call_id": c.call_id,
                            "name": c.name,
                            "args": args,
                            "say": say,
                        },
                    )
                    verdict = await _wait_approval(ap["id"], approval_timeout)
                    db.decide_approval(
                        ap["id"],
                        "approved" if verdict == "approved" else
                        ("expired" if verdict == "expired" else "denied"),
                    )
                    if verdict != "approved":
                        reason = "用户没同意，别做" if verdict == "denied" else "等太久，超时作废了"
                        res = {"ok": False, "output": reason, "ms": 0, "denied": True}
                    else:
                        res = await registry.aexecute(c.name, args, ctx)
                else:
                    res = await registry.aexecute(c.name, args, ctx)

            db.add_tool_run(
                session_id,
                c.call_id,
                c.name,
                args,
                bool(res.get("ok")),
                str(res.get("output") or ""),
                int(res.get("ms") or 0),
            )
            db.add_event(
                "tool_result",
                {"name": c.name, "ok": bool(res.get("ok")), "call_id": c.call_id},
                session_id,
            )
            yield (
                "tool_result",
                {
                    "call_id": c.call_id,
                    "name": c.name,
                    "ok": bool(res.get("ok")),
                    "output": str(res.get("output") or "")[:400],
                    "ms": int(res.get("ms") or 0),
                },
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": c.call_id,
                    "name": c.name,
                    "content": json.dumps(_result_for_model(res), ensure_ascii=False),
                }
            )

        if abort.is_set():
            break
        # 回到 while 顶部：让模型基于工具结果再说话

    # ---------------------------------------------------------------- 收尾
    final_text = "".join(content_parts).strip()
    final_thinking = "".join(thinking_parts).strip()

    if abort.is_set():
        if not final_text:
            final_text = "行，我停下了。"
            yield ("content", {"text": final_text})
    elif not finished and tool_count > 0 and round_no >= max_rounds:
        if not final_text:
            final_text = FALLBACK_MAX_ROUNDS
    if not final_text:
        # 模型什么都没说（极少数情况）——不能让前端空白，补一句并推给前端
        final_text = FALLBACK_EMPTY
        yield ("content", {"text": final_text})

    latency_ms = int((time.perf_counter() - t_start) * 1000)
    meta = {
        "model": model,
        "provider": degraded or provider_name,
        "latency_ms": latency_ms,
        "usage": usage,
        "rounds": round_no,
        "degraded": bool(degraded),
    }
    msg_id = db.add_message(
        session_id,
        "assistant",
        final_text,
        thinking=final_thinking,
        tool_calls=all_tool_calls,
        meta=meta,
    )
    db.touch_session(session_id)
    db.add_event(
        "turn_end",
        {
            "tool_count": tool_count,
            "latency_ms": latency_ms,
            "model": model,
            "degraded": bool(degraded),
        },
        session_id,
    )

    _clear_abort(session_id)

    yield (
        "turn_end",
        {
            "message_id": msg_id,
            "tool_count": tool_count,
            "latency_ms": latency_ms,
            "usage": usage,
            "model": model,
            "degraded": bool(degraded),
        },
    )


# ---------------------------------------------------------------- 非流式便捷入口（测试/脚本用）

async def run_once(session_id: str, text: str, **kw) -> dict:
    """跑一轮并把所有事件收起来，返回汇总（不用于生产，供测试）。"""
    events: list[tuple[str, dict]] = []
    text_parts: list[str] = []
    async for name, payload in run_turn(session_id, text, **kw):
        events.append((name, payload))
        if name == "content":
            text_parts.append(payload.get("text") or "")
    return {
        "text": "".join(text_parts).strip(),
        "events": events,
        "tool_calls": [p for n, p in events if n == "tool_call"],
        "approvals": [p for n, p in events if n == "approval"],
        "errors": [p for n, p in events if n == "error"],
    }
