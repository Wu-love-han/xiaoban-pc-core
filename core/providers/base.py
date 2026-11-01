"""Provider 抽象：把不同推理后端抹平成同一个事件流。

大脑只认 ProviderEvent，不认 HTTP 细节。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol


@dataclass
class ProviderEvent:
    """一次推理流里产出的事件。

    kind:
      - thinking  推理增量（reasoning_content），只给前端看，不进正文
      - content   正文增量，唯一该拼成回复的
      - tool_call 模型决定动手（arguments 已是合并好的完整 JSON 字符串）
      - done      本轮流结束（附 usage）
      - error     出错
    """

    kind: str
    text: str = ""
    # tool_call 专用
    call_id: str = ""
    name: str = ""
    arguments: str = ""
    # done 专用
    usage: dict = field(default_factory=dict)
    finish_reason: str = ""


class Provider(Protocol):
    name: str

    def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str,
        temperature: float = 0.8,
        top_p: float = 0.92,
        max_tokens: int = 1200,
        reasoning: str = "none",
    ) -> AsyncIterator[ProviderEvent]: ...


class ToolCallAccumulator:
    """把流式 tool_calls 增量按 index 合并成完整调用。

    实测：本机网关会把 arguments 切成**单字符**片段发过来，形如
      {"index":0,"function":{"arguments":"{\""}}
      {"index":0,"function":{"arguments":"path"}}
    所以必须按 index 累积拼接，不能每片当一次调用。
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict] = {}
        self._order: list[int] = []

    def feed(self, deltas: list[dict]) -> None:
        for d in deltas or []:
            idx = int(d.get("index", 0) or 0)
            if idx not in self._by_index:
                self._by_index[idx] = {"id": "", "name": "", "arguments": ""}
                self._order.append(idx)
            slot = self._by_index[idx]
            if d.get("id") and not slot["id"]:
                slot["id"] = str(d["id"])
            fn = d.get("function") or {}
            if fn.get("name") and not slot["name"]:
                slot["name"] = str(fn["name"])
            arg_piece = fn.get("arguments")
            if isinstance(arg_piece, str):
                slot["arguments"] += arg_piece
            elif isinstance(arg_piece, dict):
                # 少数实现直接给对象
                slot["arguments"] = json.dumps(arg_piece, ensure_ascii=False)

    def results(self) -> list[ProviderEvent]:
        out: list[ProviderEvent] = []
        for i, idx in enumerate(self._order):
            slot = self._by_index[idx]
            if not slot["name"]:
                continue
            out.append(
                ProviderEvent(
                    kind="tool_call",
                    call_id=slot["id"] or f"call_{idx}",
                    name=slot["name"],
                    arguments=slot["arguments"] or "{}",
                )
            )
        return out

    def clear(self) -> None:
        self._by_index.clear()
        self._order.clear()

    def __bool__(self) -> bool:
        # 只有「有名字的」才算真的收到了调用；光有 index 和半截 arguments 不算
        return any(slot["name"] for slot in self._by_index.values())


def parse_args(raw: str) -> tuple[dict, str]:
    """把模型给的 arguments 解析成 dict。

    返回 (args, error)。解析失败时 args={} 且 error 非空，
    调用方应把 error 回灌给模型让它重来，而不是直接崩。
    """
    s = (raw or "").strip()
    if not s:
        return {}, ""
    try:
        v = json.loads(s)
    except json.JSONDecodeError as exc:
        return {}, f"参数不是合法 JSON（{exc.msg}）"
    if not isinstance(v, dict):
        return {}, f"参数应该是 JSON 对象，收到的是 {type(v).__name__}"
    return v, ""
