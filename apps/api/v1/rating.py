"""评分反馈 router。跨实体通用：mcp_server / skill。"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_current_user, get_db
from exceptions import NotFoundError, ValidationError
from services import rating_service

router = APIRouter(prefix="/ratings", tags=["评分反馈"])

_ENTITY_PATH = Path(..., pattern=r"^(mcp_server|skill)$")


class RateRequest(BaseModel):
    score: int = Field(..., ge=1, le=5)
    feedback_type: str = Field("", pattern=r"^(bug|suggestion|praise)?$")
    comment: str = Field("", max_length=2000)


@router.post("/{entity_type}/{entity_id}", summary="评分资源")
async def rate_resource(
    entity_type: str = _ENTITY_PATH,
    entity_id: int = Path(..., ge=1),
    req: RateRequest = ...,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        data = await rating_service.rate(
            session,
            entity_type,
            entity_id,
            current_user["id"],
            req.score,
            req.feedback_type,
            req.comment,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=f"{e.resource} 不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "评分成功", "data": data}


@router.get("/{entity_type}/{entity_id}", summary="获取资源评分")
async def get_rating(
    entity_type: str = _ENTITY_PATH,
    entity_id: int = Path(..., ge=1),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    data = await rating_service.get_rating_view(
        session, entity_type, entity_id, current_user["id"]
    )
    return {"code": 200, "message": "ok", "data": data}


@router.get("/{entity_type}/{entity_id}/feedbacks", summary="获取资源反馈列表")
async def list_feedbacks(
    entity_type: str = _ENTITY_PATH,
    entity_id: int = Path(..., ge=1),
    feedback_type: str | None = Query(None, pattern=r"^(bug|suggestion|praise)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    data = await rating_service.list_feedbacks(
        session, entity_type, entity_id, feedback_type, page, page_size
    )
    return {"code": 200, "message": "ok", "data": data}
