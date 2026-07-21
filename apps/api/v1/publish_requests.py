from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_current_user, get_db, require_permission
from exceptions import ConflictError, NotFoundError, ValidationError
from services import publish_review_service

router = APIRouter(prefix="/publish-requests", tags=["publish-requests"])


class SubmitReviewRequest(BaseModel):
    entity_type: str = Field(..., pattern=r"^(mcp_server|skill|custom_entity)$")
    entity_id: int = Field(..., ge=1)


class ReviewActionRequest(BaseModel):
    review_notes: str = Field("", max_length=1000)


@router.get("", summary="查询发布申请列表")
async def list_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = Query(
        None, pattern=r"^(pending|approved|rejected|withdrawn)$"
    ),
    entity_type: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("publish_review:read")),
):
    data = await publish_review_service.list_reviews(
        session, status, entity_type, page, page_size
    )
    return {"code": 200, "message": "ok", "data": data}


@router.get("/{review_id}", summary="查询发布申请详情")
async def get_review(
    review_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("publish_review:read")),
):
    try:
        data = await publish_review_service.get_review(session, review_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="发布申请不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.post("", summary="提交发布申请")
async def submit_review(
    req: SubmitReviewRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        data = await publish_review_service.submit_review(
            session, req.entity_type, req.entity_id, current_user["id"]
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "发布申请已提交", "data": data}


@router.put("/{review_id}/approve", summary="审核通过发布申请")
async def approve_review(
    review_id: int,
    req: ReviewActionRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("publish_review:approve")),
):
    try:
        data = await publish_review_service.approve(
            session, review_id, current_user["id"], req.review_notes
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="发布申请不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"code": 200, "message": "发布申请已通过", "data": data}


@router.put("/{review_id}/reject", summary="审核驳回发布申请")
async def reject_review(
    review_id: int,
    req: ReviewActionRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("publish_review:approve")),
):
    try:
        data = await publish_review_service.reject(
            session, review_id, current_user["id"], req.review_notes
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="发布申请不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"code": 200, "message": "发布申请已驳回", "data": data}


@router.put("/{review_id}/withdraw", summary="撤回发布申请")
async def withdraw_review(
    review_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        data = await publish_review_service.withdraw(
            session, review_id, current_user["id"]
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="发布申请不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"code": 200, "message": "发布申请已撤回", "data": data}
