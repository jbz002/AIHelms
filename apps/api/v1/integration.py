"""AI Hub 服务间集成端点（RFC 7523 JWT Bearer Assertion 换令牌 + 身份拉取）。"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, get_integration_identity
from services import integration_service

router = APIRouter(prefix="/integration", tags=["服务集成"])


class AssertionRequest(BaseModel):
    assertion: str = Field(..., min_length=20, max_length=8192)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.post("/token", summary="签发集成访问令牌")
async def issue_integration_token(
    request: Request,
    req: AssertionRequest,
    session: AsyncSession = Depends(get_db),
):
    ip = _client_ip(request)
    await integration_service.check_token_endpoint_rate_limit(ip)
    data = await integration_service.issue_integration_token(session, req.assertion)
    return {"code": 200, "message": "集成访问令牌签发成功", "data": data}


@router.get("/identity", summary="拉取用户 AI 身份")
async def get_integration_identity_keys(
    request: Request,
    identity: dict = Depends(get_integration_identity),
    session: AsyncSession = Depends(get_db),
):
    data = await integration_service.get_integration_identity_data(
        session, identity, ip=_client_ip(request)
    )
    return {"code": 200, "message": "ok", "data": data}
