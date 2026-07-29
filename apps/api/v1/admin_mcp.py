"""内置管理员 MCP server 状态查询。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_current_user, get_db
from core.public_urls import resolve_platform_public_url
from mcp_admin.server import mcp
from repositories import api_key_repo

router = APIRouter(prefix="/admin-mcp", tags=["系统"])


@router.get("", summary="获取内置管理员 MCP 状态")
async def get_admin_mcp_status(
    request: Request,
    _: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """内置管理员 MCP 的就绪状态、接入端点、工具清单与鉴权可用性。"""
    tools = await mcp.list_tools(run_middleware=False)
    tool_names = [t.name for t in tools]
    has_active_api_key = await api_key_repo.count_active(session) > 0
    endpoint_url = resolve_platform_public_url(request) + "/admin-mcp/mcp"
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "name": mcp.name,
            "endpoint_url": endpoint_url,
            "transport": "streamable-http",
            "auth_scheme": "Bearer ak-xxx",
            "tool_count": len(tool_names),
            "tool_names": tool_names,
            "has_active_api_key": has_active_api_key,
        },
    }
