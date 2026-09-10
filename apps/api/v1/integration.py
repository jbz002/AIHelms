"""AI Hub 服务间集成端点（方式七自省验证，子应用持 AI Hub 凭证直连拉取身份）。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.aihub_verify import verify_aihub_credential
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
    caller: dict = Depends(verify_aihub_credential),
    session: AsyncSession = Depends(get_db),
):
    if caller.get("caller_type") != "user":
        raise HTTPException(status_code=403, detail="个人数据需用户凭证")
    aihub_user_id = caller.get("user_id")
    if not aihub_user_id:
        raise HTTPException(status_code=401, detail="凭证未携带用户身份")
    data = await integration_service.get_integration_identity_data(
        session, aihub_user_id, ip=_client_ip(request)
    )
    return {"code": 200, "message": "ok", "data": data}
