"""观测工具（M1）：当前可用模型、供应商 CRUD、审计日志、Dashboard、用量统计。"""

from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, error_text, json_dumps
from mcp_admin.server import mcp
from services import (
    audit_log_service,
    dashboard_service,
    model_service,
    provider_service,
    usage_stats_service,
)

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


class EmptyInput(BaseModel):
    pass


# ---------- 当前可用模型 ----------


@mcp.tool(name="admin_list_active_models", annotations=READ_ONLY)
async def admin_list_active_models(params: EmptyInput) -> str:
    """列出当前所有活跃模型（含部署，供 LLM 判断平台有哪些模型可用）。"""
    async with async_session() as session:
        try:
            data = await model_service.get_all_active_models(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


# ---------- 供应商 ----------


class ProviderIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    provider_id: int = Field(..., ge=1)


class CreateProviderInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=100)
    provider_type: str = Field(..., description="供应商类型标识")
    billing_type: str = Field(default="token", pattern="^(token|flat|mixed)$")
    monthly_budget: float | None = Field(default=None, ge=0)
    description: str = ""
    config: dict | None = None


class UpdateProviderInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    provider_id: int = Field(..., ge=1)
    name: str | None = None
    provider_type: str | None = None
    billing_type: str | None = Field(default=None, pattern="^(token|flat|mixed)$")
    monthly_budget: float | None = Field(default=None, ge=0)
    is_active: bool | None = None
    description: str | None = None
    config: dict | None = None


@mcp.tool(name="admin_list_providers", annotations=READ_ONLY)
async def admin_list_providers(params: PageInput) -> str:
    """分页查询供应商列表。"""
    async with async_session() as session:
        try:
            data = await provider_service.list_providers(
                session, params.page, params.page_size
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_provider", annotations=READ_ONLY)
async def admin_get_provider(params: ProviderIdInput) -> str:
    """按 ID 查询供应商详情。"""
    async with async_session() as session:
        try:
            data = await provider_service.get_provider_by_id(
                session, params.provider_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_provider", annotations=WRITE)
@audited_tool("admin_create_provider")
async def admin_create_provider(params: CreateProviderInput) -> str:
    """创建供应商。返回新建详情。"""
    async with async_session() as session:
        try:
            data = await provider_service.create_provider(
                session,
                params.name,
                params.provider_type,
                params.billing_type,
                params.monthly_budget,
                params.description,
                params.config,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_provider", annotations=WRITE)
@audited_tool("admin_update_provider")
async def admin_update_provider(params: UpdateProviderInput) -> str:
    """更新供应商。只传需修改字段。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await provider_service.update_provider(
                session,
                params.provider_id,
                params.name,
                params.provider_type,
                params.billing_type,
                params.monthly_budget,
                params.is_active,
                params.description,
                params.config,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_provider", annotations=DELETE)
@audited_tool("admin_delete_provider")
async def admin_delete_provider(params: ProviderIdInput) -> str:
    """删除供应商。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await provider_service.delete_provider(session, params.provider_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "provider_id": params.provider_id})


# ---------- 审计日志 ----------


class ListAuditLogsInput(PageInput):
    start_time: datetime | None = None
    end_time: datetime | None = None
    user_id: int | None = Field(default=None, ge=1)
    method: str | None = None
    status: str | None = None
    action: str | None = None


@mcp.tool(name="admin_list_audit_logs", annotations=READ_ONLY)
async def admin_list_audit_logs(params: ListAuditLogsInput) -> str:
    """分页查询管理员审计日志（含 MCP 写工具调用，path 形如 /admin-mcp/mcp#<tool>）。"""
    async with async_session() as session:
        try:
            data = await audit_log_service.list_logs(
                session,
                params.page,
                params.page_size,
                params.start_time,
                params.end_time,
                params.user_id,
                params.method,
                params.status,
                params.action,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_audit_log_filters", annotations=READ_ONLY)
async def admin_audit_log_filters(params: EmptyInput) -> str:
    """审计日志筛选项（actors / actions）。"""
    async with async_session() as session:
        try:
            data = await audit_log_service.list_filters(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


# ---------- Dashboard ----------


class DashboardInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    period: str | None = Field(default=None, description="7d|30d|current_month")
    start_date: date | None = None
    end_date: date | None = None

    def resolve(self) -> tuple[date, date]:
        if self.start_date and self.end_date:
            return self.start_date, self.end_date
        today = date.today()
        if self.period == "7d":
            return today - timedelta(days=6), today
        if self.period == "30d":
            return today - timedelta(days=29), today
        return today.replace(day=1), today


class TaskIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    task_id: str = Field(..., min_length=1)


@mcp.tool(name="admin_get_dashboard", annotations=READ_ONLY)
async def admin_get_dashboard(params: DashboardInput) -> str:
    """平台 Dashboard 汇总数据。"""
    start, end = params.resolve()
    async with async_session() as session:
        try:
            data = await dashboard_service.get_dashboard(session, start, end)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_refresh_dashboard", annotations=WRITE)
@audited_tool("admin_refresh_dashboard")
async def admin_refresh_dashboard(params: EmptyInput) -> str:
    """提交 Dashboard 数据刷新任务。"""
    try:
        data = await dashboard_service.request_refresh()
    except (NotFoundError, ConflictError, ValidationError) as e:
        return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_dashboard_refresh_status", annotations=READ_ONLY)
async def admin_dashboard_refresh_status(params: TaskIdInput) -> str:
    """查询 Dashboard 刷新任务状态。"""
    try:
        data = dashboard_service.get_refresh_status(params.task_id)
    except (NotFoundError, ConflictError, ValidationError) as e:
        return error_text(e)
    return json_dumps(data)


# ---------- 用量统计 ----------


class ServerDaysInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    server_id: int = Field(..., ge=1)
    days: int = Field(default=30, ge=1, le=365)


class SkillDaysInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    skill_id: int = Field(..., ge=1)
    days: int = Field(default=30, ge=1, le=365)


@mcp.tool(name="admin_mcp_usage_stats", annotations=READ_ONLY)
async def admin_mcp_usage_stats(params: ServerDaysInput) -> str:
    """MCP Server 用量统计（近 N 天）。"""
    async with async_session() as session:
        try:
            data = await usage_stats_service.mcp_usage_stats(
                session, params.server_id, params.days
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_skill_usage_stats", annotations=READ_ONLY)
async def admin_skill_usage_stats(params: SkillDaysInput) -> str:
    """Skill 用量统计（近 N 天）。"""
    async with async_session() as session:
        try:
            data = await usage_stats_service.skill_usage_stats(
                session, params.skill_id, params.days
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)
