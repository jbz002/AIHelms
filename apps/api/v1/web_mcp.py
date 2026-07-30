"""内置用户自助 MCP server 状态查询。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_current_user, get_db
from core.public_urls import resolve_platform_public_url
from mcp_web.server import mcp
from repositories import api_key_repo

router = APIRouter(prefix="/web-mcp", tags=["系统"])


@router.get("", summary="获取内置用户自助 MCP 状态")
async def get_web_mcp_status(
    request: Request,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """内置用户自助 MCP 的就绪状态、接入端点、工具清单与当前用户的鉴权可用性。"""
    # 绕 search transform 拿原始注册工具：transform 只压缩 tools/list 暴露数，
    # 平台注册的真实工具数（能力）不变，前端展示取注册总数
    tools = await mcp._list_tools()
    tool_names = [t.name for t in tools]
    has_active_api_key = (
        await api_key_repo.count_by_creator(session, current_user["user_id"]) > 0
    )
    endpoint_url = resolve_platform_public_url(request) + "/web-mcp/mcp"
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
