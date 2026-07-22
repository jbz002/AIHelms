"""S7 阶段一 · CLI 令牌管理端点（admin）。

复用 ai_keys 表的 CLI scoped token，由 admin 创建/查看/编辑/撤销。
写操作 summary 必填（审计日志 action 字段依赖）。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from exceptions import NotFoundError, ValidationError
from services import cli_token_service

router = APIRouter(prefix="/cli-tokens", tags=["cli-tokens"])


class CreateCliTokenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    scopes: list[str] = Field(default_factory=list)
    owner_id: int = Field(..., ge=1)
    owner_type: str = Field("user", pattern=r"^(user|department|project)$")
    expires_at: datetime | None = Field(default=None)


class UpdateCliTokenRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    scopes: list[str] | None = None
    is_active: bool | None = None


@router.post("", summary="创建 CLI 令牌")
async def create_cli_token(
    req: CreateCliTokenRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("cli_token:create")),
):
    try:
        data, _raw = await cli_token_service.create_token(
            session,
            name=req.name,
            description=req.description,
            scopes=req.scopes,
            owner_id=req.owner_id,
            owner_type=req.owner_type,
            expires_at=req.expires_at,
            created_by=current_user["id"],
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "CLI 令牌创建成功", "data": data}


@router.get("")
async def list_cli_tokens(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    owner_id: int | None = Query(None, ge=1),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("cli_token:read")),
):
    data = await cli_token_service.list_tokens(session, page, page_size, owner_id)
    return {"code": 200, "message": "ok", "data": data}


@router.get("/{token_id}")
async def get_cli_token(
    token_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("cli_token:read")),
):
    try:
        data = await cli_token_service.get_token(session, token_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="CLI 令牌不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.put("/{token_id}", summary="更新 CLI 令牌")
async def update_cli_token(
    token_id: int,
    req: UpdateCliTokenRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("cli_token:update")),
):
    try:
        data = await cli_token_service.update_token(
            session,
            token_id,
            name=req.name,
            description=req.description,
            scopes=req.scopes,
            is_active=req.is_active,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="CLI 令牌不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "CLI 令牌更新成功", "data": data}


@router.put("/{token_id}/toggle", summary="切换 CLI 令牌启用状态")
async def toggle_cli_token(
    token_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("cli_token:update")),
):
    try:
        current = await cli_token_service.get_token(session, token_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="CLI 令牌不存在")
    data = await cli_token_service.update_token(
        session, token_id, is_active=not current["is_active"]
    )
    return {"code": 200, "message": "CLI 令牌状态已切换", "data": data}


@router.delete("/{token_id}", summary="撤销 CLI 令牌")
async def delete_cli_token(
    token_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("cli_token:delete")),
):
    try:
        await cli_token_service.revoke_token(session, token_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="CLI 令牌不存在")
    return {"code": 200, "message": "CLI 令牌已撤销", "data": None}
