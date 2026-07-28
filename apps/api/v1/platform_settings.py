from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from services import platform_settings_service

router = APIRouter(prefix="/platform-settings", tags=["平台设置"])


class UpdatePlatformSettingsRequest(BaseModel):
    default_model_id: int | None = None


@router.get("", summary="查询平台设置")
async def get_settings(
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("platform_settings:read")),
):
    data = await platform_settings_service.get_settings(session)
    return {"code": 200, "message": "ok", "data": data}


@router.put("", summary="更新平台设置")
async def update_settings(
    req: UpdatePlatformSettingsRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("platform_settings:config")),
):
    data = await platform_settings_service.update_default_model(
        session, req.default_model_id, current_user
    )
    return {"code": 200, "message": "平台设置已更新", "data": data}
