"""OpenAI 兼容 provider：本机 Magpie 网关（默认大脑）。

实测事实（2026-11-01，本机 3425 端口）：
- 支持原生 function calling：`tools` + `tool_choice:auto` 能正常返回 tool_calls。
- 支持流式：SSE，`data: {...}` 行，末尾 `data: [DONE]`。
- **流式 tool_calls 的 arguments 被切成单字符片段**，必须按 index 拼接。
- `reasoning_effort: "none"` 能显著降低首字延迟（实测 6.6s → 3.2s）。
- 推理内容在 `delta.reasoning_content`。
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

from .base import ProviderEvent, ToolCallAccumulator

logger = logging.getLogger("pccore.provider.openai")


class OpenAICompatProvider:
    name = "gateway"

    def __init__(self, conf: dict, name: str = "gateway") -> None:
        self.name = name
        self.base_url = str(conf.get("base_url") or "http://127.0.0.1:3425/v1").rstrip("/")
        self.api_key = str(conf.get("api_key") or "")
        self.timeout_s = float(conf.get("timeout_s") or 180)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _payload(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str,
        temperature: float,
        top_p: float,
        max_tokens: int,
        reasoning: str,
    ) -> dict:
        p: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        if tools:
            p["tools"] = tools
            p["tool_choice"] = "auto"
        if reasoning:
            # none 关掉思考链，首字快很多；high/max 用于难题
            p["reasoning_effort"] = reasoning
        return p

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
        payload = self._payload(
            messages, tools,
            model=model, temperature=temperature, top_p=top_p,
            max_tokens=max_tokens, reasoning=reasoning,
        )
        acc = ToolCallAccumulator()
        usage: dict = {}
        finish = ""

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout_s, connect=8.0),
                headers=self._headers(),
            ) as client:
                async with client.stream("POST", "/chat/completions", json=payload) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", "replace")
                        yield ProviderEvent(
                            kind="error",
                            text=f"{self.name} 返回 {resp.status_code}：{body[:300]}",
                        )
                        return

                    async for line in resp.aiter_lines():
                        line = (line or "").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        if isinstance(obj.get("error"), dict):
                            yield ProviderEvent(
                                kind="error",
                                text=str(obj["error"].get("message") or obj["error"])[:300],
                            )
                            return

                        if obj.get("usage"):
                            usage = obj["usage"]

                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        ch = choices[0]
                        if ch.get("finish_reason"):
                            finish = str(ch["finish_reason"])
                        delta = ch.get("delta") or {}

                        rc = delta.get("reasoning_content") or delta.get("reasoning") or ""
                        if rc:
                            yield ProviderEvent(kind="thinking", text=rc)

                        piece = delta.get("content") or ""
                        if piece:
                            yield ProviderEvent(kind="content", text=piece)

                        tcs = delta.get("tool_calls")
                        if tcs:
                            acc.feed(tcs)

        except httpx.ConnectError:
            yield ProviderEvent(
                kind="error",
                text=f"连不上推理服务 {self.base_url}（网关没开？）",
            )
            return
        except httpx.ReadTimeout:
            yield ProviderEvent(kind="error", text=f"推理超时（>{self.timeout_s:.0f}s）")
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("provider 流式异常")
            yield ProviderEvent(kind="error", text=f"{type(exc).__name__}: {exc}")
            return

        for ev in acc.results():
            yield ev

        yield ProviderEvent(
            kind="done",
            usage={
                "in": int(usage.get("prompt_tokens") or 0),
                "out": int(usage.get("completion_tokens") or 0),
            },
            finish_reason=finish,
        )

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(8.0, connect=4.0),
                headers=self._headers(),
            ) as client:
                r = await client.get("/models")
                ok = r.status_code < 400
                return {
                    "ok": ok,
                    "provider": self.name,
                    "base_url": self.base_url,
                    "status": r.status_code,
                }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "provider": self.name,
                "base_url": self.base_url,
                "error": f"{type(exc).__name__}: {exc}",
            }
