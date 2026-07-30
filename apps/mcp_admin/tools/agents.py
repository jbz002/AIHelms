"""Agent 资源治理工具（M5）：CRUD/发布/分类/平台/解析Key/用量日志。"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, actor_id, error_text, json_dumps
from mcp_admin.server import mcp
from services import agent_service

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


class AgentIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    agent_id: int = Field(..., ge=1)


class ListAgentsInput(PageInput):
    category: str | None = None
    platform: str | None = None
    is_published: bool | None = None


class CreateAgentInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=100)
    platform: str = Field(..., description="平台标识（见 list_platforms）")
    description: str = ""
    category: str = "general"
    chat_url: str = ""
    external_id: str = ""
    icon_url: str | None = None
    tags: list | None = None
    is_published: bool = False
    requires_approval: bool = False
    department_id: int | None = Field(default=None, ge=1)
    project_id: int | None = Field(default=None, ge=1)


class UpdateAgentInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    agent_id: int = Field(..., ge=1)
    name: str | None = None
    description: str | None = None
    category: str | None = None
    chat_url: str | None = None
    external_id: str | None = None
    icon_url: str | None = None
    tags: list | None = None
    is_published: bool | None = None
    requires_approval: bool | None = None
    department_id: int | None = Field(default=None, ge=1)
    project_id: int | None = Field(default=None, ge=1)


class AgentBoolInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    agent_id: int = Field(..., ge=1)
    value: bool


class ResolveKeyInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    agent_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)


class AgentUsageLogsInput(PageInput):
    agent_id: int = Field(..., ge=1)
    user_id: int | None = Field(default=None, ge=1)


class CategoryNameInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    sort_order: int = 0


class CategoryIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    category_id: int = Field(..., ge=1)


class PlatformNameInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=64)
    label: str = ""
    description: str = ""
    sort_order: int = 0


class PlatformIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    platform_id: int = Field(..., ge=1)


class EmptyInput(BaseModel):
    pass


@mcp.tool(name="admin_list_agents", annotations=READ_ONLY)
async def admin_list_agents(params: ListAgentsInput) -> str:
    """分页查询 Agent 列表。"""
    async with async_session() as session:
        try:
            data = await agent_service.list_agents(
                session,
                params.page,
                params.page_size,
                params.category,
                params.platform,
                params.is_published,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_agent", annotations=READ_ONLY)
async def admin_get_agent(params: AgentIdInput) -> str:
    """查询 Agent 详情。"""
    async with async_session() as session:
        try:
            data = await agent_service.get_agent(session, params.agent_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_agent", annotations=WRITE)
@audited_tool("admin_create_agent")
async def admin_create_agent(params: CreateAgentInput) -> str:
    """创建 Agent。返回新建详情。"""
    created_by = actor_id()
    async with async_session() as session:
        try:
            data = await agent_service.create_agent(
                session,
                name=params.name,
                platform=params.platform,
                description=params.description,
                category=params.category,
                chat_url=params.chat_url,
                external_id=params.external_id,
                icon_url=params.icon_url,
                tags=params.tags,
                is_published=params.is_published,
                requires_approval=params.requires_approval,
                department_id=params.department_id,
                project_id=params.project_id,
                created_by=created_by,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_agent", annotations=WRITE)
@audited_tool("admin_update_agent")
async def admin_update_agent(params: UpdateAgentInput) -> str:
    """更新 Agent 字段（None 字段不变）。返回更新后详情。"""
    kwargs = params.model_dump(exclude={"agent_id"}, exclude_none=True)
    async with async_session() as session:
        try:
            data = await agent_service.update_agent(session, params.agent_id, **kwargs)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_agent", annotations=DELETE)
@audited_tool("admin_delete_agent")
async def admin_delete_agent(params: AgentIdInput) -> str:
    """删除 Agent。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await agent_service.delete_agent(session, params.agent_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "agent_id": params.agent_id})


@mcp.tool(name="admin_set_agent_published", annotations=WRITE)
@audited_tool("admin_set_agent_published")
async def admin_set_agent_published(params: AgentBoolInput) -> str:
    """设置 Agent 发布状态。返回 {updated:true}。"""
    async with async_session() as session:
        try:
            await agent_service.set_published(session, params.agent_id, params.value)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {"updated": True, "agent_id": params.agent_id, "is_published": params.value}
    )


@mcp.tool(name="admin_list_agent_categories", annotations=READ_ONLY)
async def admin_list_agent_categories(params: EmptyInput) -> str:
    """列出 Agent 分类。"""
    async with async_session() as session:
        try:
            data = await agent_service.list_categories(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_agent_category", annotations=WRITE)
@audited_tool("admin_create_agent_category")
async def admin_create_agent_category(params: CategoryNameInput) -> str:
    """创建 Agent 分类。返回新建详情。"""
    async with async_session() as session:
        try:
            data = await agent_service.create_category(
                session, params.name, params.description, params.sort_order
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_agent_category", annotations=DELETE)
@audited_tool("admin_delete_agent_category")
async def admin_delete_agent_category(params: CategoryIdInput) -> str:
    """删除 Agent 分类。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await agent_service.delete_category(session, params.category_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "category_id": params.category_id})


@mcp.tool(name="admin_list_agent_platforms", annotations=READ_ONLY)
async def admin_list_agent_platforms(params: EmptyInput) -> str:
    """列出 Agent 平台（如 dify/coze 等）。"""
    async with async_session() as session:
        try:
            data = await agent_service.list_platforms(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_agent_platform", annotations=WRITE)
@audited_tool("admin_create_agent_platform")
async def admin_create_agent_platform(params: PlatformNameInput) -> str:
    """创建 Agent 平台。返回新建详情。"""
    async with async_session() as session:
        try:
            data = await agent_service.create_platform(
                session,
                params.name,
                params.label,
                params.description,
                params.sort_order,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_agent_platform", annotations=DELETE)
@audited_tool("admin_delete_agent_platform")
async def admin_delete_agent_platform(params: PlatformIdInput) -> str:
    """删除 Agent 平台。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await agent_service.delete_platform(session, params.platform_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "platform_id": params.platform_id})


@mcp.tool(name="admin_resolve_agent_key", annotations=READ_ONLY)
async def admin_resolve_agent_key(params: ResolveKeyInput) -> str:
    """解析用户访问指定 Agent 所需的 Key/接入信息。"""
    async with async_session() as session:
        try:
            data = await agent_service.resolve_key(
                session, params.agent_id, params.user_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_list_agent_usage_logs", annotations=READ_ONLY)
async def admin_list_agent_usage_logs(params: AgentUsageLogsInput) -> str:
    """分页查询 Agent 用量日志。"""
    async with async_session() as session:
        try:
            data = await agent_service.list_usage_logs(
                session,
                params.agent_id,
                params.page,
                params.page_size,
                params.user_id,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)
