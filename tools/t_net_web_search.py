"""net.web_search：联网搜索（ddgs 库）。

为什么写得这么啰嗦：ddgs 是「抓别人的搜索页」，各后端随时会限流/挂掉，
单一后端失败是常态，不是异常。所以这里按后端逐个试，全挂了才报失败，
并且失败信息里写清「是网络问题还是没结果」——模型需要知道该不该重试。

超时策略：ddgs 的 timeout 是**单次请求**超时，后端串起来最多要好几十秒。
这里用整体预算（config.search.timeout_s 放宽到 3 倍作为总预算）兜住，
超预算就返回已经拿到的结果或失败，绝不让大脑卡死。
"""

from __future__ import annotations

import time
from typing import Any

from . import _common as C

# 依次尝试的后端。实测（2026-11，本机）：yahoo 最快最稳（3s），bing 常要 16-18s 且
# 有时直接超时，duckduckgo 在国内基本不通，mojeek 慢。所以 yahoo 放第一个，
# 让它先兜住绝大多数查询，后面的只是兜底。
_BACKENDS = ("yahoo", "bing", "mojeek", "duckduckgo")


def _norm_items(raw: list, limit: int) -> list[dict]:
    """ddgs 各后端字段名不完全一样（body/snippet/description），统一成一套。"""
    out: list[dict] = []
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        url = str(it.get("href") or it.get("url") or it.get("link") or "").strip()
        body = str(
            it.get("body") or it.get("snippet") or it.get("description") or ""
        ).strip()
        if not (title or url):
            continue
        out.append({"title": title, "url": url, "snippet": body})
        if len(out) >= limit:
            break
    return out


def run(args: dict, ctx: Any) -> dict:
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        return C.fail("要搜什么呢？query 是空的。", "MissingArg: query")

    if not bool(C.cfg_get(ctx, "search.enabled", True)):
        return C.fail("配置里把联网搜索关掉了（search.enabled = false）。", "SearchDisabled")

    limit = int(args.get("max_results") or C.cfg_get(ctx, "search.max_results", 5) or 5)
    limit = max(1, min(limit, 10))
    region = str(C.cfg_get(ctx, "search.region", "cn-zh") or "cn-zh")
    timeout_s = float(C.cfg_get(ctx, "search.timeout_s", 10) or 10)
    budget = max(timeout_s, 6.0) * 3  # 整体预算：够试两三个后端

    try:
        from ddgs import DDGS  # type: ignore
    except ImportError:
        return C.fail(
            "这台机器的 Python 里没装 ddgs，联网搜索用不了。"
            "换装了 ddgs 的解释器，或者直接用 net.fetch 抓一个具体网址。",
            "ImportError: ddgs",
        )

    t0 = time.monotonic()
    errors: list[str] = []
    items: list[dict] = []

    for backend in _BACKENDS:
        if time.monotonic() - t0 > budget:
            errors.append(f"总预算 {budget:.0f}s 用完")
            break
        try:
            raw = DDGS(timeout=timeout_s).text(
                query, max_results=limit, region=region, backend=backend
            )
            items = _norm_items(raw, limit)
            if items:
                break
            errors.append(f"{backend}: 没结果")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{backend}: {type(exc).__name__}")

    if not items:
        return C.fail(
            f"没搜到「{query}」。可能是网络不通或者搜索源都被限流了"
            f"（{'；'.join(errors[:3])}）。换个说法再试，或者给我一个具体网址我用 net.fetch 抓。",
            "SearchFailed: " + "; ".join(errors[:4]),
        )

    lines = []
    for i, it in enumerate(items, 1):
        snip = it["snippet"]
        if len(snip) > 110:
            snip = snip[:110] + "…"
        lines.append(f"{i}. {it['title']}\n   {snip}\n   {it['url']}")

    out = f"「{query}」搜到 {len(items)} 条：\n" + "\n".join(lines)
    return C.ok(
        out,
        query=query,
        count=len(items),
        items=items,
        elapsed_ms=int((time.monotonic() - t0) * 1000),
    )


TOOL = {
    "name": "net.web_search",
    "title": "联网搜索",
    "desc": "用搜索引擎查一个关键词，返回前几条结果的标题、摘要和链接。想知道最新的、本机没有的信息时用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "max_results": {
                "type": "integer",
                "description": "要几条（1-10，默认取配置里的 5）",
            },
        },
        "required": ["query"],
    },
    "run": C.guard(run),
}
