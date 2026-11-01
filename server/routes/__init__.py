"""路由包。

一个模块一组接口，全部挂 `/api` 前缀：

| 模块 | 负责 |
|---|---|
| `system`     | `/api/health`（不鉴权）、`/api/config` |
| `sessions`   | 会话 CRUD |
| `chat`       | `/api/chat`（SSE）、`/api/abort/{sid}` |
| `tools_api`  | `/api/tools`、`/api/events` |
| `approvals`  | `/api/approvals` 列表与决定 |

鉴权依赖挂在各 router 上（`dependencies=[Depends(require_auth)]`），
只有 `system.public_router` 例外。
"""

from __future__ import annotations

__all__ = ["system", "sessions", "chat", "tools_api", "approvals"]
