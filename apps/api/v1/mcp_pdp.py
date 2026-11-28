"""PDP 接口：`POST /api/v1/mcp/authorize`（P2）。

调用方是 mcp_proxy，用 AIHelms 签发的**服务令牌**（`sk_sa_`）认证；管理员/用户 JWT 也可调
（便于排障与演练，语义按人类 actor 处理）。

契约见 `03` §5。`decision=deny` 时调用方要把 `reason_code` 本地化成工具级错误
（JSON-RPC `isError`），**不是** HTTP 403——403 会让客户端把整个 server 判成连不上。
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_current_user, get_db
from repositories import user_repo
from services import mcp_pdp, service_account_service

router = APIRouter(prefix="/mcp", tags=["MCP 授权决策"])


class Subject(BaseModel):
    type: str = Field("user", pattern="^(user|aihub_user)$")
    id: int | str | None = None


class Actor(BaseModel):
    kind: str = Field("human", pattern="^(human|service)$")
    service_account_id: int | None = Field(None, ge=1)
    client: str | None = Field(None, max_length=64)


class AuthorizeRequest(BaseModel):
    subject: Subject | None = None
    actor: Actor = Field(default_factory=Actor)
    server: str = Field(..., min_length=1, max_length=128)
    tool: str | None = Field(None, max_length=200)
    context: dict = Field(default_factory=dict)


async def pdp_caller(
    request: Request, session: AsyncSession = Depends(get_db)
) -> dict:
    """服务令牌优先；否则按普通用户身份（JWT / 平台 API Key）处理。"""
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer sk_sa_"):
        sa = await service_account_service.verify_token(
            session, auth.split(" ", 1)[1]
        )
        if sa is None:
            raise HTTPException(status_code=401, detail="服务令牌无效或已停用")
        return {"kind": "service", "service_account_id": sa.id, "name": sa.name}
    user = await get_current_user(request)
    return {"kind": "user", "user_id": user["id"], "is_admin": user["is_admin"]}


async def _resolve_subject_id(
    session: AsyncSession, subject: Subject | None
) -> int | None:
    if subject is None or subject.id is None:
        return None
    if subject.type == "user":
        return int(subject.id)
    # 只查不建：PDP 是热路径，未知 aihub id 不能顺手建档
    user = await user_repo.find_user_by_aihub_user_id(session, str(subject.id))
    return user.id if user else None


@router.post("/authorize", summary="MCP 工具调用授权决策（PDP）")
async def authorize(
    req: AuthorizeRequest,
    session: AsyncSession = Depends(get_db),
    caller: dict = Depends(pdp_caller),
):
    subject_id = await _resolve_subject_id(session, req.subject)
    actor_kind = req.actor.kind
    actor_sa_id = req.actor.service_account_id
    if caller["kind"] == "service":
        # 服务令牌调用时，actor 默认就是调用方自己；声明成 human 说明是 mcp_proxy
        # 在代理一个人类会话，此时不需要 actor_service_account_id 参与委托判定。
        if actor_kind == "service" and actor_sa_id is None:
            actor_sa_id = caller["service_account_id"]

    decision = await mcp_pdp.authorize(
        session,
        subject_type="user" if subject_id is not None else "anonymous",
        subject_id=subject_id,
        actor_kind=actor_kind,
        actor_service_account_id=actor_sa_id,
        server_name=req.server,
        tool_name=req.tool,
        trace_id=(req.context or {}).get("trace_id"),
    )
    return {"code": 200, "data": decision.to_dict()}
