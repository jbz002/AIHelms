"""MCP Server 资源治理深化工具（M5）：CRUD/发布/版本/工具/计费/分类。"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import actor_id, error_text, json_dumps
from mcp_admin.server import mcp
from services import mcp_service

READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}
DELETE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": False,
}


class ServerIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    server_id: int = Field(..., ge=1)


class CreateMcpServerInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=100)
    server_name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., description="MCP Server URL")
    transport: str = Field(default="sse", pattern="^(sse|streamable_http|stdio)$")
    auth_type: str = Field(default="none", pattern="^(none|bearer|oauth2|basic)$")
    credentials: dict | None = None
    description: str = ""
    instructions: str = ""
    category: str = "general"
    icon_url: str = ""
    is_published: bool = False
    visibility_type: str = "all"
    requires_approval: bool = False


class UpdateMcpServerInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    server_id: int = Field(..., ge=1)
    name: str | None = None
    description: str | None = None
    url: str | None = None
    transport: str | None = None
    auth_type: str | None = None
    credentials: dict | None = None
    category: str | None = None
    icon_url: str | None = None
    instructions: str | None = None
    is_published: bool | None = None
    visibility_type: str | None = None
    requires_approval: bool | None = None


class McpBoolInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    server_id: int = Field(..., ge=1)
    value: bool


class ServerVersionIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    server_id: int = Field(..., ge=1)
    version_id: int = Field(..., ge=1)


class CreateMcpVersionInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    server_id: int = Field(..., ge=1)
    version: str = Field(..., min_length=1)
    url: str = Field(..., description="该版本 MCP Server URL")
    transport: str = Field(..., pattern="^(sse|streamable_http|stdio)$")
    version_label: str = ""
    auth_type: str = "none"
    credentials: dict | None = None
    instructions: str = ""
    change_log: str = ""


class ToolBillingInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    tool_id: int = Field(..., ge=1)
    billing_type: str | None = Field(default=None, pattern="^(per_call|free|token)$")
    internal_cost_per_call: float | None = Field(default=None, ge=0)
    external_cost_per_call: float | None = Field(default=None, ge=0)


class CategoryNameInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    sort_order: int = 0


class CategoryIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    category_id: int = Field(..., ge=1)


@mcp.tool(name="admin_create_mcp_server", annotations=WRITE)
@audited_tool("admin_create_mcp_server")
async def admin_create_mcp_server(params: CreateMcpServerInput) -> str:
    """创建 MCP Server（核心参数；高级字段走 Web UI）。返回新建详情。"""
    created_by = actor_id()
    async with async_session() as session:
        try:
            data = await mcp_service.create_server(
                session,
                name=params.name,
                server_name=params.server_name,
                url=params.url,
                transport=params.transport,
                auth_type=params.auth_type,
                credentials=params.credentials,
                description=params.description,
                instructions=params.instructions,
                category=params.category,
                icon_url=params.icon_url,
                is_published=params.is_published,
                visibility_type=params.visibility_type,
                requires_approval=params.requires_approval,
                created_by=created_by,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_mcp_server", annotations=WRITE)
@audited_tool("admin_update_mcp_server")
async def admin_update_mcp_server(params: UpdateMcpServerInput) -> str:
    """更新 MCP Server 字段（None 字段不变）。返回更新后详情。"""
    actor = actor_id()
    kwargs = params.model_dump(exclude={"server_id"}, exclude_none=True)
    async with async_session() as session:
        try:
            data = await mcp_service.update_server(
                session, params.server_id, actor, **kwargs
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_mcp_server", annotations=DELETE)
@audited_tool("admin_delete_mcp_server")
async def admin_delete_mcp_server(params: ServerIdInput) -> str:
    """删除 MCP Server。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await mcp_service.delete_server(session, params.server_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "server_id": params.server_id})


@mcp.tool(name="admin_set_mcp_published", annotations=WRITE)
@audited_tool("admin_set_mcp_published")
async def admin_set_mcp_published(params: McpBoolInput) -> str:
    """设置 MCP Server 发布状态。返回 {updated:true}。"""
    async with async_session() as session:
        try:
            await mcp_service.set_published(session, params.server_id, params.value)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {"updated": True, "server_id": params.server_id, "is_published": params.value}
    )


@mcp.tool(name="admin_list_mcp_versions", annotations=READ_ONLY)
async def admin_list_mcp_versions(params: ServerIdInput) -> str:
    """列出 MCP Server 全部版本。"""
    async with async_session() as session:
        try:
            data = await mcp_service.list_versions(session, params.server_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_mcp_version", annotations=WRITE)
@audited_tool("admin_create_mcp_version")
async def admin_create_mcp_version(params: CreateMcpVersionInput) -> str:
    """创建 MCP Server 新版本。返回新版本详情。"""
    created_by = actor_id()
    async with async_session() as session:
        try:
            data = await mcp_service.create_version(
                session,
                params.server_id,
                version=params.version,
                url=params.url,
                transport=params.transport,
                version_label=params.version_label,
                auth_type=params.auth_type,
                credentials=params.credentials,
                instructions=params.instructions,
                change_log=params.change_log,
                created_by=created_by,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_activate_mcp_version", annotations=WRITE)
@audited_tool("admin_activate_mcp_version")
async def admin_activate_mcp_version(params: ServerVersionIdInput) -> str:
    """激活 MCP Server 指定版本。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await mcp_service.activate_version(
                session, params.server_id, params.version_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_deprecate_mcp_version", annotations=WRITE)
@audited_tool("admin_deprecate_mcp_version")
async def admin_deprecate_mcp_version(params: ServerVersionIdInput) -> str:
    """弃用 MCP Server 指定版本。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await mcp_service.deprecate_version(
                session, params.server_id, params.version_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_mcp_tools", annotations=READ_ONLY)
async def admin_get_mcp_tools(params: ServerIdInput) -> str:
    """列出 MCP Server 的工具清单。"""
    async with async_session() as session:
        try:
            data = await mcp_service.get_tools(session, params.server_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_mcp_tool_billing", annotations=WRITE)
@audited_tool("admin_update_mcp_tool_billing")
async def admin_update_mcp_tool_billing(params: ToolBillingInput) -> str:
    """更新 MCP 工具的计费配置。返回更新后工具。"""
    async with async_session() as session:
        try:
            data = await mcp_service.update_tool_billing(
                session,
                params.tool_id,
                params.billing_type,
                params.internal_cost_per_call,
                params.external_cost_per_call,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_list_mcp_categories", annotations=READ_ONLY)
async def admin_list_mcp_categories(params: ServerIdInput) -> str:
    """列出 MCP 分类。"""
    async with async_session() as session:
        try:
            data = await mcp_service.list_categories(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_mcp_category", annotations=WRITE)
@audited_tool("admin_create_mcp_category")
async def admin_create_mcp_category(params: CategoryNameInput) -> str:
    """创建 MCP 分类。返回新建详情。"""
    async with async_session() as session:
        try:
            data = await mcp_service.create_category(
                session, params.name, params.description, params.sort_order
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_mcp_category", annotations=DELETE)
@audited_tool("admin_delete_mcp_category")
async def admin_delete_mcp_category(params: CategoryIdInput) -> str:
    """删除 MCP 分类。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await mcp_service.delete_category(session, params.category_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "category_id": params.category_id})
