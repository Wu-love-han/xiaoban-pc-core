"""Ollama provider：断网/网关没开时的本地兜底。

Ollama 原生 /api/chat 支持 tools（新版），但流式 tool_calls 形态与 OpenAI 不同：
- 它是**整块**给出 `message.tool_calls`，不是增量 delta。
- 流式时一般最后一个 chunk 才带 done 和统计数据。

这里做两件事：
1. 流式拿 content / thinking 增量；
2. tool_calls 不管流式非流式，统一按「整块」收集。
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

from .base import ProviderEvent

logger = logging.getLogger("pccore.provider.ollama")


class OllamaProvider:
    name = "ollama"

    def __init__(self, conf: dict) -> None:
        self.base_url = str(conf.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
        self.timeout_s = float(conf.get("timeout_s") or 300)
        self.num_ctx = int(conf.get("num_ctx") or 8192)

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str,
        temperature: float = 0.8,
        top_p: float = 0.92,
        max_tokens: int = 1200,
        reasoning: str = "none",
    ) -> AsyncIterator[ProviderEvent]:
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": "30m",
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "num_predict": max_tokens,
                "num_ctx": self.num_ctx,
            },
        }
        if tools:
            payload["tools"] = tools

        collected: list[dict] = []
        usage = {"in": 0, "out": 0}
        finish = ""

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout_s, connect=8.0),
            ) as client:
                async with client.stream("POST", "/api/chat", json=payload) as resp:
                    if resp.status_code == 404:
                        body = (await resp.aread()).decode("utf-8", "replace")
                        yield ProviderEvent(
                            kind="error",
                            text=f"模型 {model} 不存在，先 ollama pull {model}（{body[:120]}）",
                        )
                        return
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", "replace")
                        yield ProviderEvent(
                            kind="error", text=f"Ollama 返回 {resp.status_code}：{body[:300]}"
                        )
                        return

                    async for line in resp.aiter_lines():
                        line = (line or "").strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("error"):
                            yield ProviderEvent(kind="error", text=str(obj["error"])[:300])
                            return

                        msg = obj.get("message") or {}
                        think = msg.get("thinking") or ""
                        if think:
                            yield ProviderEvent(kind="thinking", text=think)
                        piece = msg.get("content") or ""
                        if piece:
                            yield ProviderEvent(kind="content", text=piece)
                        for tc in msg.get("tool_calls") or []:
                            collected.append(tc)

                        if obj.get("done"):
                            usage = {
                                "in": int(obj.get("prompt_eval_count") or 0),
                                "out": int(obj.get("eval_count") or 0),
                            }
                            finish = str(obj.get("done_reason") or "")

        except httpx.ConnectError:
            yield ProviderEvent(
                kind="error",
                text=f"连不上 Ollama {self.base_url}（服务没起？）",
            )
            return
        except httpx.ReadTimeout:
            yield ProviderEvent(kind="error", text=f"Ollama 超时（>{self.timeout_s:.0f}s）")
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("ollama 流式异常")
            yield ProviderEvent(kind="error", text=f"{type(exc).__name__}: {exc}")
            return

        for i, tc in enumerate(collected):
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            if not name:
                continue
            args = fn.get("arguments")
            if isinstance(args, dict):
                args_s = json.dumps(args, ensure_ascii=False)
            else:
                args_s = str(args or "{}")
            yield ProviderEvent(
                kind="tool_call",
                call_id=str(tc.get("id") or f"call_{i}"),
                name=name,
                arguments=args_s,
            )

        yield ProviderEvent(kind="done", usage=usage, finish_reason=finish)

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=httpx.Timeout(8.0, connect=4.0)
            ) as client:
                r = await client.get("/api/tags")
                return {
                    "ok": r.status_code < 400,
                    "provider": "ollama",
                    "base_url": self.base_url,
                    "status": r.status_code,
                }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "provider": "ollama",
                "base_url": self.base_url,
                "error": f"{type(exc).__name__}: {exc}",
            }
