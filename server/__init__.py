"""pc-core 服务端（FastAPI）。

分层：`web → server → core → tools`。
本包只做三件事，**不含业务逻辑**：
  1. 把 HTTP 请求翻译成 core 的调用（路由）
  2. 把 core 的事件流翻译成 SSE（sse.py）
  3. 校验 X-PC-Token（auth.py）

契约见 `docs/CONTRACT.md` 第四、五节。
"""

from __future__ import annotations

__all__ = ["main"]
