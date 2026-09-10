"""AI Hub 服务间集成端点（方式六 HMAC 验签，AI Hub 直接签名调用拉取身份）。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.aihub_verify import verify_aihub
from core.deps import get_db
from services import integration_service

router = APIRouter(prefix="/integration", tags=["服务集成"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.get("/identity", summary="拉取用户 AI 身份")
async def get_integration_identity_keys(
    request: Request,
    on_behalf_of: str | None = Depends(verify_aihub),
    session: AsyncSession = Depends(get_db),
):
    if not on_behalf_of:
        raise HTTPException(status_code=400, detail="缺少 X-AIHub-On-Behalf-Of 头")
    data = await integration_service.get_integration_identity_data(
        session, on_behalf_of, ip=_client_ip(request)
    )
    return {"code": 200, "message": "ok", "data": data}
