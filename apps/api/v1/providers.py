from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from exceptions import ConflictError, NotFoundError
from services import model_service, provider_service

router = APIRouter(prefix="/providers", tags=["providers"])


class CreateProviderRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    provider_type: str = Field(..., min_length=1, max_length=50)
    billing_type: str = Field("token", pattern=r"^(token|per_call|monthly_quota)$")
    monthly_budget: float | None = None
    description: str = ""
    config: dict | None = None


class UpdateProviderRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    provider_type: str | None = None
    billing_type: str | None = Field(None, pattern=r"^(token|per_call|monthly_quota)$")
    monthly_budget: float | None = None
    is_active: bool | None = None
    description: str | None = None
    config: dict | None = None


@router.get("")
async def list_providers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("user:read")),
):
    result = await provider_service.list_providers(session, page, page_size)
    return {"code": 200, "message": "ok", "data": result}


@router.get("/{provider_id}/resolved-prefix", summary="查询供应商解析前缀")
async def get_resolved_prefix(
    provider_id: int,
    format: str = Query("openai", max_length=20),
    category: str = Query("chat", max_length=50),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("user:read")),
):
    """返回 (provider_type, format, category) 解析出的最终 LiteLLM 前缀及来源。

    source: override（覆盖表）/ derived（registry 派生）/ none。取代前端读 JSONB 副本。
    """
    resolved = await model_service.resolve_prefix_for_preview(
        session, provider_id, format, category
    )
    return {"code": 200, "message": "ok", "data": resolved}


@router.post("", summary="创建供应商")
async def create_provider(
    req: CreateProviderRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("user:update")),
):
    provider = await provider_service.create_provider(
        session,
        name=req.name,
        provider_type=req.provider_type,
        billing_type=req.billing_type,
        monthly_budget=req.monthly_budget,
        description=req.description,
        config=req.config,
    )
    return {"code": 200, "message": "供应商创建成功", "data": provider}


@router.get("/{provider_id}")
async def get_provider(
    provider_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("user:read")),
):
    try:
        provider = await provider_service.get_provider_by_id(session, provider_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return {"code": 200, "message": "ok", "data": provider}


@router.put("/{provider_id}", summary="更新供应商")
async def update_provider(
    provider_id: int,
    req: UpdateProviderRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("user:update")),
):
    try:
        provider = await provider_service.update_provider(
            session,
            provider_id,
            name=req.name,
            provider_type=req.provider_type,
            billing_type=req.billing_type,
            monthly_budget=req.monthly_budget,
            is_active=req.is_active,
            description=req.description,
            config=req.config,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return {"code": 200, "message": "供应商更新成功", "data": provider}


@router.delete("/{provider_id}", summary="删除供应商")
async def delete_provider(
    provider_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("user:delete")),
):
    try:
        await provider_service.delete_provider(session, provider_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="供应商不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"code": 200, "message": "供应商删除成功", "data": None}
