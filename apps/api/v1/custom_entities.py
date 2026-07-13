"""
自定义实体 API 路由
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from exceptions import NotFoundError, ValidationError, ConflictError
from services import custom_entity_service

router = APIRouter(prefix="/custom-entities", tags=["custom-entities"])


# ─── 请求模型 ───────────────────────────────────────────────────────────────


class CreateTypeRequest(BaseModel):
    type_key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=2000)
    icon: str = Field("🧩", max_length=20)
    schema_definition: dict = Field(default_factory=dict)
    searchable_fields: list[str] = Field(default_factory=list)
    is_published: bool = False


class UpdateTypeRequest(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None
    icon: str | None = Field(None, max_length=20)
    schema_definition: dict | None = None
    is_published: bool | None = None


class CreateEntityRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    data: dict = Field(..., min_length=1)
    description: str = Field("", max_length=2000)
    tags: list[str] | None = None
    is_published: bool = False
    visibility_type: str = Field("all", pattern=r"^(all|selected|private)$")
    requires_approval: bool = False


class UpdateEntityRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    data: dict | None = None
    description: str | None = None
    tags: list[str] | None = None
    is_published: bool | None = None
    visibility_type: str | None = Field(None, pattern=r"^(all|selected|private)$")


# ─── 类型管理端点 ─────────────────────────────────────────────────────────


@router.get("/types", summary="查看自定义实体类型")
async def list_types(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    is_active: bool | None = None,
    is_published: bool | None = None,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("custom_entity:read")),
):
    """查看自定义实体类型列表"""
    data = await custom_entity_service.list_types(
        session, page, page_size, is_active, is_published
    )
    return {"code": 200, "message": "ok", "data": data}


@router.get("/types/{type_id}", summary="查看自定义实体类型详情")
async def get_type(
    type_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("custom_entity:read")),
):
    """查看自定义实体类型详情"""
    try:
        data = await custom_entity_service.get_type(session, type_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="自定义实体类型不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.post("/types", summary="创建自定义实体类型")
async def create_type(
    req: CreateTypeRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("custom_entity:create")),
):
    """创建自定义实体类型"""
    try:
        data = await custom_entity_service.create_type(
            session,
            type_key=req.type_key,
            display_name=req.display_name,
            description=req.description,
            icon=req.icon,
            schema_definition=req.schema_definition,
            searchable_fields=req.searchable_fields,
            is_published=req.is_published,
            created_by=current_user["id"],
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "自定义实体类型创建成功", "data": data}


@router.put("/types/{type_id}", summary="更新自定义实体类型")
async def update_type(
    type_id: int,
    req: UpdateTypeRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("custom_entity:update")),
):
    """更新自定义实体类型"""
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        data = await custom_entity_service.update_type(session, type_id, **kwargs)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="自定义实体类型不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "自定义实体类型更新成功", "data": data}


@router.delete("/types/{type_id}", summary="删除自定义实体类型")
async def delete_type(
    type_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("custom_entity:delete")),
):
    """删除自定义实体类型"""
    try:
        await custom_entity_service.delete_type(session, type_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="自定义实体类型不存在")
    return {"code": 200, "message": "自定义实体类型删除成功", "data": None}


# ─── 实例管理端点 ─────────────────────────────────────────────────────────


@router.get("", summary="查看自定义实体实例")
async def list_entities(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    type_key: str | None = None,
    is_published: bool | None = None,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("custom_entity:read")),
):
    """查看自定义实体实例列表"""
    data = await custom_entity_service.list_entities(
        session, page, page_size, type_key, is_published
    )
    return {"code": 200, "message": "ok", "data": data}


@router.get("/{entity_id}", summary="查看自定义实体实例详情")
async def get_entity(
    entity_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("custom_entity:read")),
):
    """查看自定义实体实例详情"""
    try:
        data = await custom_entity_service.get_entity(session, entity_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="自定义实体实例不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.post("/{type_key}", summary="创建自定义实体实例")
async def create_entity(
    type_key: str,
    req: CreateEntityRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("custom_entity:create")),
):
    """创建自定义实体实例"""
    try:
        data = await custom_entity_service.create_entity(
            session,
            type_key=type_key,
            name=req.name,
            data=req.data,
            description=req.description,
            tags=req.tags,
            is_published=req.is_published,
            visibility_type=req.visibility_type,
            requires_approval=req.requires_approval,
            created_by=current_user["id"],
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "自定义实体实例创建成功", "data": data}


@router.put("/{entity_id}", summary="更新自定义实体实例")
async def update_entity(
    entity_id: int,
    req: UpdateEntityRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("custom_entity:update")),
):
    """更新自定义实体实例"""
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        data = await custom_entity_service.update_entity(session, entity_id, **kwargs)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="自定义实体实例不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "自定义实体实例更新成功", "data": data}


@router.delete("/{entity_id}", summary="删除自定义实体实例")
async def delete_entity(
    entity_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("custom_entity:delete")),
):
    """删除自定义实体实例"""
    try:
        await custom_entity_service.delete_entity(session, entity_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="自定义实体实例不存在")
    return {"code": 200, "message": "自定义实体实例删除成功", "data": None}
