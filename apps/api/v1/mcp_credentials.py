"""Token Broker 接口（P2-F4）：`/api/v1/mcp/credentials/*`。

调用方是 mcp_proxy，用 AIHelms 签发的服务令牌（`sk_sa_`）认证——契约（`03` §6）要求
不再靠来源 IP。开关关闭时整体 404，老路径（ai-assistant 本地换票）不受影响。

响应里**带票**（调用方要用它注入出站头），审计与日志**不带**。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.mcp_pdp import pdp_caller
from core.config import settings
from core.deps import get_db
from models.db import User
from services import credential_broker

router = APIRouter(prefix="/mcp/credentials", tags=["MCP 凭据"])


class Subject(BaseModel):
    type: str = Field("aihub_user", pattern="^(user|aihub_user)$")
    id: int | str | None = None


class Actor(BaseModel):
    kind: str = Field("human", pattern="^(human|service)$")
    client: str | None = Field(None, max_length=64)


class ExchangeRequest(BaseModel):
    subject: Subject
    target: str = Field(..., min_length=1, max_length=64)
    actor: Actor = Field(default_factory=Actor)


class InvalidateRequest(BaseModel):
    subject: Subject
    target: str = Field(..., min_length=1, max_length=64)
    actor: Actor = Field(default_factory=Actor)


def _require_enabled() -> None:
    if not settings.mcp_credential_broker_enabled:
        raise HTTPException(status_code=404, detail="Token Broker 未启用")


async def _subject_id(session: AsyncSession, subject: Subject) -> str | None:
    """统一成 AI Hub 用户 id（换票的身份连接键在 AI Hub）。"""
    if subject.id is None:
        return None
    if subject.type == "aihub_user":
        return str(subject.id).strip() or None
    # type=user：AIHelms 本地 id → aihub_user_id（只查不建）
    row = await session.execute(
        select(User.aihub_user_id).where(User.id == int(subject.id))
    )
    aihub_id = row.scalar_one_or_none()
    return str(aihub_id).strip() if aihub_id else None


@router.post("/exchange", summary="换票：主体 → 目标平台短时委托票")
async def exchange(
    req: ExchangeRequest,
    session: AsyncSession = Depends(get_db),
    caller: dict = Depends(pdp_caller),
):
    _require_enabled()
    subject_id = await _subject_id(session, req.subject)
    if not subject_id:
        # 缺主体一律按「未绑定」拒：换票是热路径，不猜
        return {
            "code": 200,
            "data": {
                "ok": False,
                "reason_code": credential_broker.R_SUBJECT_NOT_BOUND,
                "provider": "",
            },
        }

    result = await credential_broker.exchange(
        session,
        subject_type=req.subject.type,
        subject_id=subject_id,
        target=req.target,
        actor_kind=req.actor.kind,
    )
    return {"code": 200, "data": result.to_dict()}


@router.post("/invalidate", summary="作废缓存（下游 403 时由调用方触发）")
async def invalidate(
    req: InvalidateRequest,
    session: AsyncSession = Depends(get_db),
    caller: dict = Depends(pdp_caller),
):
    _require_enabled()
    subject_id = await _subject_id(session, req.subject)
    if not subject_id:
        return {"code": 200, "data": {"deleted": False}}

    deleted = await credential_broker.invalidate(
        subject_type=req.subject.type,
        subject_id=subject_id,
        target=req.target,
        actor_kind=req.actor.kind,
    )
    return {"code": 200, "data": {"deleted": deleted}}
