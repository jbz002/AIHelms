"""导出任务 + 统一搜索工具（M7）。"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, actor, error_text, json_dumps
from mcp_admin.server import mcp
from services import export_task_service, search_service

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


def _current_user() -> dict:
    a = actor()
    return {"id": a["user_id"], "username": a["username"], "is_admin": True}


# ---------- 导出任务 ----------


class ListExportTasksInput(PageInput):
    source: str | None = None
    status: str | None = None


class TaskIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    task_id: int = Field(..., ge=1)


class CreateExportTaskInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    source: str = Field(..., description="导出来源（如 llm_logs/mcp_logs/audit_logs）")
    export_type: str = Field(..., description="导出格式（如 csv/xlsx）")
    params: dict = Field(default_factory=dict, description="导出筛选参数")
    task_name: str = ""


class CleanupInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    retention_days: int = Field(default=30, ge=1, description="清理超过 N 天的任务")


@mcp.tool(name="admin_list_export_tasks", annotations=READ_ONLY)
async def admin_list_export_tasks(params: ListExportTasksInput) -> str:
    """分页查询导出任务。"""
    async with async_session() as session:
        try:
            data = await export_task_service.list_export_tasks(
                session, params.page, params.page_size, params.source, params.status
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_export_task", annotations=READ_ONLY)
async def admin_get_export_task(params: TaskIdInput) -> str:
    """查询导出任务详情。"""
    async with async_session() as session:
        try:
            task = await export_task_service.get_export_task(session, params.task_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    if task is None:
        return error_text(NotFoundError("export_task", params.task_id))
    data = {c.name: getattr(task, c.name) for c in task.__table__.columns}
    return json_dumps(data)


@mcp.tool(name="admin_create_export_task", annotations=WRITE)
@audited_tool("admin_create_export_task")
async def admin_create_export_task(params: CreateExportTaskInput) -> str:
    """创建导出任务（异步处理，返回任务详情）。"""
    cu = _current_user()
    async with async_session() as session:
        try:
            data = await export_task_service.create_export_task(
                session,
                params.source,
                params.export_type,
                params.params,
                cu,
                params.task_name,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_retry_export_task", annotations=WRITE)
@audited_tool("admin_retry_export_task")
async def admin_retry_export_task(params: TaskIdInput) -> str:
    """重试失败的导出任务。返回更新后任务。"""
    cu = _current_user()
    async with async_session() as session:
        try:
            data = await export_task_service.retry_export_task(
                session, params.task_id, cu
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_cancel_export_task", annotations=WRITE)
@audited_tool("admin_cancel_export_task")
async def admin_cancel_export_task(params: TaskIdInput) -> str:
    """取消导出任务。返回更新后任务。"""
    async with async_session() as session:
        try:
            data = await export_task_service.cancel_export_task(session, params.task_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_cleanup_export_tasks", annotations=WRITE)
@audited_tool("admin_cleanup_export_tasks")
async def admin_cleanup_export_tasks(params: CleanupInput) -> str:
    """清理超过保留期的导出任务。返回清理统计。"""
    async with async_session() as session:
        try:
            data = await export_task_service.cleanup_export_tasks(
                session, params.retention_days
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


# ---------- 统一搜索 ----------


class UnifiedSearchInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    keyword: str = Field(..., min_length=1, description="搜索关键词")
    entity_types: list[str] | None = Field(
        default=None, description="限定实体类型（如 model/mcp/skill/agent/user）"
    )
    category: str | None = None
    is_published: bool | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


@mcp.tool(name="admin_unified_search", annotations=READ_ONLY)
async def admin_unified_search(params: UnifiedSearchInput) -> str:
    """跨实体统一搜索（模型/MCP/Skill/Agent/User 等）。"""
    async with async_session() as session:
        try:
            data = await search_service.unified_search(
                session,
                params.keyword,
                params.entity_types,
                params.category,
                params.is_published,
                params.page,
                params.page_size,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)
