from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from services import publish_settings_service

router = APIRouter(prefix="/publish-settings", tags=["publish-settings"])


class UpdatePublishSettingsRequest(BaseModel):
    enabled: bool


@router.get("", summary="查询发布门控设置")
async def get_settings(
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("publish_review:read")),
):
    data = await publish_settings_service.get_settings(session)
    return {"code": 200, "message": "ok", "data": data}


@router.put("", summary="更新发布门控设置")
async def update_settings(
    req: UpdatePublishSettingsRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("publish_review:config")),
):
    data = await publish_settings_service.update_settings(
        session, req.enabled, current_user
    )
    return {"code": 200, "message": "发布门控设置已更新", "data": data}
