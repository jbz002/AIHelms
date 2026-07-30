"""市场浏览工具。"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import NotFoundError, ValidationError
from mcp_web._common import PageInput, actor, error_text, json_dumps
from mcp_web.server import mcp
from services import mcp_service, skill_service
from services.visibility_service import can_access


class SearchSkillsInput(PageInput):
    category: str | None = Field(default=None, description="分类过滤")


class SearchMcpsInput(PageInput):
    category: str | None = Field(default=None, description="分类过滤")


class ResourceDetailInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    type: str = Field(
        ..., pattern=r"^(skill|mcp)$", description="资源类型：skill 或 mcp"
    )
    id: int = Field(..., ge=1, description="资源 ID")


@mcp.tool(
    name="web_search_published_skills",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def web_search_published_skills(params: SearchSkillsInput) -> str:
    """搜索市场已发布的 Skill 列表。返回 JSON：{items, total, page, page_size}。"""
    ident = actor()
    async with async_session() as session:
        data = await skill_service.list_skills(
            session,
            params.page,
            params.page_size,
            params.category,
            is_published=True,
            viewer_id=ident["user_id"],
            is_admin=ident["is_admin"],
        )
    return json_dumps(data)


@mcp.tool(
    name="web_search_published_mcps",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def web_search_published_mcps(params: SearchMcpsInput) -> str:
    """搜索市场已发布的 MCP Server 列表。返回 JSON：{items, total, page, page_size}。"""
    ident = actor()
    async with async_session() as session:
        data = await mcp_service.list_servers(
            session,
            params.page,
            params.page_size,
            params.category,
            is_active=None,
            is_published=True,
            status=None,
            viewer_id=ident["user_id"],
            is_admin=ident["is_admin"],
        )
    return json_dumps(data)


@mcp.tool(
    name="web_get_resource_detail",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def web_get_resource_detail(params: ResourceDetailInput) -> str:
    """查询市场资源详情（skill 或 mcp）。受可见性控制：private 仅创建者与管理员可读。"""
    ident = actor()
    async with async_session() as session:
        try:
            if params.type == "skill":
                data = await skill_service.get_skill(session, params.id)
            else:
                data = await mcp_service.get_server(session, params.id)
        except (NotFoundError, ValidationError) as e:
            return error_text(e)
    if not can_access(
        ident["user_id"],
        ident["is_admin"],
        data.get("visibility_type", "all"),
        data.get("created_by"),
    ):
        return "错误：无权访问该资源"
    return json_dumps(data)
