"""MCP Server 管理工具（P0：读 + 工具刷新 + 健康检查）。"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, error_text, json_dumps
from mcp_admin.server import mcp
from services import mcp_service


class ListServersInput(PageInput):
    category: str | None = Field(default=None, description="按分类过滤")
    is_active: bool | None = None
    is_published: bool | None = None


class ServerIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    server_id: int = Field(..., ge=1)


@mcp.tool(
    name="admin_list_mcp_servers",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_list_mcp_servers(params: ListServersInput) -> str:
    """分页查询 MCP Server 列表（管理员视角）。返回 {items,total,page,page_size}。"""
    async with async_session() as session:
        try:
            data = await mcp_service.list_servers(
                session,
                params.page,
                params.page_size,
                params.category,
                params.is_active,
                params.is_published,
                is_admin=True,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_get_mcp_server",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_get_mcp_server(params: ServerIdInput) -> str:
    """按 ID 查询 MCP Server 详情（含工具列表）。"""
    async with async_session() as session:
        try:
            data = await mcp_service.get_server(session, params.server_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_refresh_mcp_tools",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_refresh_mcp_tools")
async def admin_refresh_mcp_tools(params: ServerIdInput) -> str:
    """刷新 MCP Server 的工具列表（经 LiteLLM 拉远端，可能超时/失败）。返回最新工具列表。"""
    async with async_session() as session:
        try:
            data = await mcp_service.refresh_tools(session, params.server_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_health_check_mcp",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_health_check_mcp")
async def admin_health_check_mcp(params: ServerIdInput) -> str:
    """对 MCP Server 发起健康检查（经 LiteLLM 探测远端连通性）。返回检查结果。"""
    async with async_session() as session:
        try:
            data = await mcp_service.health_check_server(session, params.server_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)
