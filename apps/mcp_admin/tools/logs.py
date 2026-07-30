"""调用日志工具（M1）：LLM / MCP / Skill / Agent 调用日志的查询与筛选项。只读。"""

from datetime import datetime

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._common import PageInput, error_text, json_dumps
from mcp_admin.server import mcp
from services import usage_log_service

READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


class EmptyInput(BaseModel):
    pass


class LogIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    log_id: int = Field(..., ge=1)


class ListLlmLogsInput(PageInput):
    start_time: datetime | None = None
    end_time: datetime | None = None
    user_id: int | None = Field(default=None, ge=1)
    ai_key_id: int | None = Field(default=None, ge=1)
    model: str | None = None
    models: list[str] | None = None
    provider: str | None = None
    status: str | None = None


@mcp.tool(name="admin_list_llm_logs", annotations=READ_ONLY)
async def admin_list_llm_logs(params: ListLlmLogsInput) -> str:
    """分页查询 LLM 调用日志。返回 {items,total,page,page_size}。"""
    async with async_session() as session:
        try:
            data = await usage_log_service.list_llm_logs(
                session,
                params.page,
                params.page_size,
                params.start_time,
                params.end_time,
                params.user_id,
                params.ai_key_id,
                params.model,
                params.models,
                params.provider,
                params.status,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_llm_log", annotations=READ_ONLY)
async def admin_get_llm_log(params: LogIdInput) -> str:
    """按 ID 查询 LLM 调用日志详情。"""
    async with async_session() as session:
        try:
            data = await usage_log_service.get_llm_log(session, params.log_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_llm_log_filters", annotations=READ_ONLY)
async def admin_llm_log_filters(params: EmptyInput) -> str:
    """LLM 日志筛选项（可用 model/provider/status 等）。"""
    async with async_session() as session:
        try:
            data = await usage_log_service.llm_filters(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class ListMcpLogsInput(PageInput):
    start_time: datetime | None = None
    end_time: datetime | None = None
    user_id: int | None = Field(default=None, ge=1)
    ai_key_id: int | None = Field(default=None, ge=1)
    server_id: int | None = Field(default=None, ge=1)
    tool_name: str | None = None
    status: str | None = None


@mcp.tool(name="admin_list_mcp_logs", annotations=READ_ONLY)
async def admin_list_mcp_logs(params: ListMcpLogsInput) -> str:
    """分页查询 MCP 调用日志。"""
    async with async_session() as session:
        try:
            data = await usage_log_service.list_mcp_logs(
                session,
                params.page,
                params.page_size,
                params.start_time,
                params.end_time,
                params.user_id,
                params.ai_key_id,
                params.server_id,
                params.tool_name,
                params.status,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_mcp_log", annotations=READ_ONLY)
async def admin_get_mcp_log(params: LogIdInput) -> str:
    """按 ID 查询 MCP 调用日志详情。"""
    async with async_session() as session:
        try:
            data = await usage_log_service.get_mcp_log(session, params.log_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_mcp_log_filters", annotations=READ_ONLY)
async def admin_mcp_log_filters(params: EmptyInput) -> str:
    """MCP 日志筛选项。"""
    async with async_session() as session:
        try:
            data = await usage_log_service.mcp_filters(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class ListSkillLogsInput(PageInput):
    start_time: datetime | None = None
    end_time: datetime | None = None
    user_id: int | None = Field(default=None, ge=1)
    skill_id: int | None = Field(default=None, ge=1)
    action: str | None = None


@mcp.tool(name="admin_list_skill_logs", annotations=READ_ONLY)
async def admin_list_skill_logs(params: ListSkillLogsInput) -> str:
    """分页查询 Skill 调用日志。"""
    async with async_session() as session:
        try:
            data = await usage_log_service.list_skill_logs(
                session,
                params.page,
                params.page_size,
                params.start_time,
                params.end_time,
                params.user_id,
                params.skill_id,
                params.action,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_skill_log_filters", annotations=READ_ONLY)
async def admin_skill_log_filters(params: EmptyInput) -> str:
    """Skill 日志筛选项。"""
    async with async_session() as session:
        try:
            data = await usage_log_service.skill_filters(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class ListAgentLogsInput(PageInput):
    start_time: datetime | None = None
    end_time: datetime | None = None
    user_id: int | None = Field(default=None, ge=1)
    agent_id: int | None = Field(default=None, ge=1)
    platform: str | None = None


@mcp.tool(name="admin_list_agent_logs", annotations=READ_ONLY)
async def admin_list_agent_logs(params: ListAgentLogsInput) -> str:
    """分页查询 Agent 调用日志。"""
    async with async_session() as session:
        try:
            data = await usage_log_service.list_agent_logs(
                session,
                params.page,
                params.page_size,
                params.start_time,
                params.end_time,
                params.user_id,
                params.agent_id,
                params.platform,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_agent_log_filters", annotations=READ_ONLY)
async def admin_agent_log_filters(params: EmptyInput) -> str:
    """Agent 日志筛选项。"""
    async with async_session() as session:
        try:
            data = await usage_log_service.agent_filters(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)
