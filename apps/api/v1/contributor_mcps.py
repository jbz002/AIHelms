"""贡献者 MCP router — 普通用户在 web 端贡献自己的 MCP Server 草稿。

与 admin 的 mcp.py 正交：
- 守卫统一 require_permission("mcp:contribute")（admin 由 is_admin 放行，无需此码）。
- 所有权强制：每个端点经 _require_owned 比对 McpServer.created_by == 当前用户，404 非 403。
- 草稿语义：create 硬编码 is_published=False / requires_approval=True，防绕审核直接发布。
- 版本激活、安全审查、审核通过/驳回仍归 admin（mcp:update / ai_policies:scan / publish_review:approve）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import McpServer
from repositories import mcp_repo
from services import mcp_service, publish_review_service

router = APIRouter(prefix="/contributor/mcps", tags=["贡献者 MCP"])


class CreateMcpRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    server_name: str = Field(..., min_length=1, max_length=128)
    url: str = Field(..., min_length=1, max_length=2048)
    transport: str = Field(
        "sse", pattern=r"^(sse|http|streamable_http|streamableHttp)$"
    )
    auth_type: str = Field("none", max_length=30)
    description: str = Field("", max_length=2000)
    instructions: str = Field("", max_length=5000)
    category: str = Field("general", max_length=50)
    tags: list[str] | None = None
    author: str = Field("", max_length=128)
    icon_url: str = Field("", max_length=500)
    documentation_url: str = Field("", max_length=500)
    source_url: str = Field("", max_length=500)

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        return v


class UpdateMcpRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    server_name: str | None = Field(None, min_length=1, max_length=128)
    auth_type: str | None = Field(None, max_length=30)
    description: str | None = None
    instructions: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    author: str | None = Field(None, max_length=128)
    icon_url: str | None = Field(None, max_length=500)
    documentation_url: str | None = None
    source_url: str | None = None


class CreateMcpVersionRequest(BaseModel):
    version: str = Field(..., min_length=1, max_length=64)
    url: str = Field(..., min_length=1, max_length=2048)
    transport: str = Field(
        "sse", pattern=r"^(sse|http|streamable_http|streamableHttp)$"
    )
    change_log: str = Field("", max_length=5000)

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        return v


async def _require_owned(session: AsyncSession, server_id: int, uid: int) -> McpServer:
    """加载 MCP Server 并校验归属当前用户；不存在或不归属均返回 404。"""
    server = await mcp_repo.find_server_by_id(session, server_id)
    if not server or server.created_by != uid:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    return server


@router.get("", summary="我的 MCP Server 列表")
async def list_my_mcps(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:contribute")),
):
    uid = current_user["id"]
    items = await mcp_repo.find_all_servers_by_creator(session, uid, page, page_size)
    total = await mcp_repo.count_servers_by_creator(session, uid)
    serialized = [mcp_service._serialize_server(s) for s in items]
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "items": serialized,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@router.get("/{server_id}", summary="我的 MCP Server 详情")
async def get_my_mcp(
    server_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:contribute")),
):
    await _require_owned(session, server_id, current_user["id"])
    try:
        data = await mcp_service.get_server(session, server_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.post("", summary="创建我的 MCP Server 草稿")
async def create_my_mcp(
    req: CreateMcpRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:contribute")),
):
    try:
        data = await mcp_service.create_server(
            session,
            name=req.name,
            server_name=req.server_name,
            url=req.url,
            transport=req.transport,
            auth_type=req.auth_type,
            description=req.description,
            instructions=req.instructions,
            category=req.category,
            tags=req.tags,
            author=req.author,
            icon_url=req.icon_url,
            documentation_url=req.documentation_url,
            source_url=req.source_url,
            is_published=False,
            requires_approval=True,
            created_by=current_user["id"],
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "MCP Server 草稿创建成功", "data": data}


@router.put("/{server_id}", summary="更新我的 MCP Server 草稿")
async def update_my_mcp(
    server_id: int,
    req: UpdateMcpRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:contribute")),
):
    server = await _require_owned(session, server_id, current_user["id"])
    if server.is_published:
        raise HTTPException(
            status_code=409,
            detail="已发布的 MCP Server 不可编辑，如需改接入地址请新建版本",
        )
    kwargs = req.model_dump(exclude_none=True)
    try:
        data = await mcp_service.update_server(
            session, server_id, actor_id=current_user["id"], **kwargs
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "MCP Server 更新成功", "data": data}


@router.post("/{server_id}/versions", summary="创建我的 MCP Server 新版本")
async def create_my_mcp_version(
    server_id: int,
    req: CreateMcpVersionRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:contribute")),
):
    await _require_owned(session, server_id, current_user["id"])
    try:
        data = await mcp_service.create_version(
            session,
            server_id,
            version=req.version,
            url=req.url,
            transport=req.transport,
            change_log=req.change_log,
            created_by=current_user["id"],
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "MCP 版本创建成功", "data": data}


@router.delete("/{server_id}", summary="删除我的 MCP Server 草稿")
async def delete_my_mcp(
    server_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:contribute")),
):
    server = await _require_owned(session, server_id, current_user["id"])
    if server.is_published:
        raise HTTPException(
            status_code=409, detail="已发布的 MCP Server 不可删除，请联系管理员"
        )
    try:
        await mcp_service.delete_server(session, server_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    return {"code": 200, "message": "MCP Server 删除成功", "data": None}


@router.post("/{server_id}/submit-review", summary="提交我的 MCP Server 发布审核")
async def submit_my_mcp_review(
    server_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:contribute")),
):
    server = await _require_owned(session, server_id, current_user["id"])
    if server.is_published:
        raise HTTPException(
            status_code=409, detail="MCP Server 已发布，无需重复提交审核"
        )
    try:
        review = await publish_review_service.submit_review(
            session,
            publish_review_service.ENTITY_MCP,
            server_id,
            current_user["id"],
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "code": 200,
        "message": "发布审核已提交",
        "data": publish_review_service._serialize(review),
    }
