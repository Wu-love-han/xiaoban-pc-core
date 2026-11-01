"""审批接口（契约 3.4 / 第五节 / 第七节）。

危险工具（pc.write_file / pc.delete / pc.shell）执行前，brain 会：
  1. `db.create_approval()` 建一条 pending 记录
  2. yield 一个 `approval` 事件（带人格化的 `say`）
  3. `await _wait_approval(approval_id, 300s)` 挂在 Future 上等这里唤醒

所以本模块的 POST 要做两件事，而且顺序不能反：
  - 先把 DB 状态从 pending 改成 approved/denied（这是**唯一权威**，
    前端刷新页面后看到的就是这个状态，也防重复点击）；
  - 再 `brain.resolve_approval()` 唤醒挂着的协程。

## 为什么要重试唤醒

brain 在 `yield approval` 之后才 `await _wait_approval()` 注册 Future。
事件推给前端到用户点击之间通常够长，但理论上存在「Future 还没注册好，
点击就到了」的窗口。`resolve_approval` 返回 False 就说明撞上了这个窗口，
这里用几十毫秒级的短重试兜住，避免这一轮白等 300 秒超时。
**不改 brain**，只在服务端等它一下。
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel

from core import db

from ..auth import require_auth

logger = logging.getLogger("pccore.api.approvals")

router = APIRouter(prefix="/api/approvals", tags=["approvals"], dependencies=[Depends(require_auth)])

#: 唤醒重试：总共约 2 秒。再多就没意义了 —— 前端不会比这更快。
_RESOLVE_RETRIES = 40
_RESOLVE_GAP_S = 0.05

MAX_LIMIT = 200


class DecisionIn(BaseModel):
    """`{"decision": "approve" | "deny"}`"""

    decision: str = ""


def _load_brain():
    try:
        from core import brain  # noqa: PLC0415 - brain 可能还没就绪，延迟导入

        return brain
    except Exception as exc:  # noqa: BLE001
        logger.warning("core.brain 导入失败：%s: %s", type(exc).__name__, exc)
        return None


async def _wake_brain(approval_id: str, approved: bool) -> bool:
    """尽力唤醒大脑里等这个审批的协程。唤醒不了不算失败（可能已经超时了）。"""
    brain = _load_brain()
    fn = getattr(brain, "resolve_approval", None) if brain is not None else None
    if not callable(fn):
        return False
    for _ in range(_RESOLVE_RETRIES):
        try:
            if fn(approval_id, approved):
                return True
        except Exception:  # noqa: BLE001
            logger.exception("resolve_approval 失败：%s", approval_id)
            return False
        await asyncio.sleep(_RESOLVE_GAP_S)
    return False


@router.get("")
async def list_approvals(
    status: str = Query(default="pending"),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
):
    """GET /api/approvals?status=pending → {items:[...]}

    `status` 传空串表示不过滤。
    """
    try:
        items = db.list_approvals(status=(status or "").strip(), limit=limit)
        return {"ok": True, "items": items}
    except Exception as exc:  # noqa: BLE001
        logger.exception("列审批失败")
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.post("/{approval_id}")
async def decide(
    approval_id: str = Path(..., description="approval id，形如 a_xxxxx"),
    body: DecisionIn | None = None,
):
    """POST /api/approvals/{id} `{"decision":"approve"|"deny"}` → {ok, status}"""
    try:
        raw = (body.decision if body else "") or ""
        d = raw.strip().lower()
        if d in ("approve", "approved", "yes", "ok", "allow", "true", "1"):
            approved, new_status = True, "approved"
        elif d in ("deny", "denied", "no", "reject", "false", "0"):
            approved, new_status = False, "denied"
        else:
            return {"ok": False, "status": "", "error": f"decision 只能是 approve 或 deny，收到：{raw!r}"}

        row = db.get_approval(approval_id)
        if row is None:
            return {"ok": False, "status": "", "error": "没有这条审批记录"}

        cur_status = str(row.get("status") or "")
        if cur_status != "pending":
            # 重复点击 / 已经超时：如实回报当前状态，但不报错（前端据此把卡片置灰）。
            return {
                "ok": True,
                "status": cur_status,
                "already_decided": True,
                "approval_id": approval_id,
            }

        # 1) DB 是权威：只有 pending 能被改，天然防并发重复点击
        changed = db.decide_approval(approval_id, new_status)
        if not changed:
            latest = db.get_approval(approval_id) or {}
            return {
                "ok": True,
                "status": str(latest.get("status") or ""),
                "already_decided": True,
                "approval_id": approval_id,
            }

        # 2) 再唤醒挂着的 brain 协程
        woken = await _wake_brain(approval_id, approved)
        if not woken:
            logger.info("审批 %s 已置为 %s，但没找到等待中的协程（可能已超时）", approval_id, new_status)

        try:
            db.add_event(
                "approval_decision",
                {"approval_id": approval_id, "status": new_status, "name": row.get("name")},
                str(row.get("session_id") or ""),
            )
        except Exception:  # noqa: BLE001
            pass

        return {
            "ok": True,
            "status": new_status,
            "approval_id": approval_id,
            "woken": woken,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("处理审批失败：%s", approval_id)
        return {"ok": False, "status": "", "error": f"{type(exc).__name__}: {exc}"}
