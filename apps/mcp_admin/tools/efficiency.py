"""AI 效能与观测工具（M1）：效能总览/趋势/成本/预算/采用/健康/报告。只读为主。

管理员全局视角（Q17 决议：不传 scope=self，actor 已校验 is_admin）。
"""

from datetime import date, timedelta

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, actor_id, error_text, json_dumps
from mcp_admin.server import mcp
from services import (
    efficiency_budget_service,
    efficiency_cost_service,
    efficiency_health_service,
    efficiency_report_service,
    efficiency_service,
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


class PeriodInput(BaseModel):
    """效能查询时间范围：period 与 start_date/end_date 二选一。"""

    model_config = {"str_strip_whitespace": True}
    period: str | None = Field(
        default=None, description="7d|30d|current_month；与 start_date/end_date 二选一"
    )
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


class ScopeInput(PeriodInput):
    dimension: str = Field(default="department", pattern="^(department|project)$")
    scope_ids: list[int] = Field(default_factory=list, description="部门或项目 ID")

    def resolve_scopes(self) -> tuple[list[int] | None, list[int] | None]:
        dept = self.scope_ids if self.dimension == "department" else None
        proj = self.scope_ids if self.dimension == "project" else None
        return dept, proj


class EmptyInput(BaseModel):
    pass


class OverviewInput(ScopeInput):
    granularity: str = Field(default="day", pattern="^(day|week|month)$")


@mcp.tool(name="admin_efficiency_overview", annotations=READ_ONLY)
async def admin_efficiency_overview(params: OverviewInput) -> str:
    """AI 效能总览（多维分析，管理员全局视角）。"""
    start, end = params.resolve()
    dept, proj = params.resolve_scopes()
    async with async_session() as session:
        try:
            data = await efficiency_service.get_overview(
                session, start, end, params.granularity, params.dimension, dept, proj
            )
            if isinstance(data, dict):
                data["freshness"] = await efficiency_service.get_freshness(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class TrendInput(PeriodInput):
    granularity: str = Field(default="day", pattern="^(day|week|month)$")


@mcp.tool(name="admin_efficiency_trend", annotations=READ_ONLY)
async def admin_efficiency_trend(params: TrendInput) -> str:
    """效能趋势（按时间桶聚合）。"""
    start, end = params.resolve()
    async with async_session() as session:
        try:
            data = await efficiency_service.get_trend(
                session, start, end, params.granularity
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class CostInput(ScopeInput):
    cost_type: str = Field(default="all", description="资源类型；空=all")


@mcp.tool(name="admin_efficiency_cost", annotations=READ_ONLY)
async def admin_efficiency_cost(params: CostInput) -> str:
    """成本分析（按维度/资源类型）。"""
    start, end = params.resolve()
    dept, proj = params.resolve_scopes()
    async with async_session() as session:
        try:
            data = await efficiency_cost_service.get_cost(
                session, start, end, params.cost_type, dept, params.dimension, proj
            )
            if isinstance(data, dict):
                data["freshness"] = await efficiency_service.get_freshness(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class CostDetailInput(ScopeInput):
    tab: str = Field(default="department")
    cost_type: str = Field(default="all")


@mcp.tool(name="admin_efficiency_cost_detail", annotations=READ_ONLY)
async def admin_efficiency_cost_detail(params: CostDetailInput) -> str:
    """成本明细（按 tab 下钻）。"""
    start, end = params.resolve()
    dept, proj = params.resolve_scopes()
    async with async_session() as session:
        try:
            data = await efficiency_cost_service.get_cost_detail(
                session,
                start,
                end,
                params.tab,
                params.cost_type,
                dept,
                params.dimension,
                proj,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class TopUsersInput(ScopeInput):
    metric: str = Field(default="cost", pattern="^(cost|tokens|requests)$")
    cost_type: str = Field(default="all")


@mcp.tool(name="admin_efficiency_top_users", annotations=READ_ONLY)
async def admin_efficiency_top_users(params: TopUsersInput) -> str:
    """Top 用户榜（按 metric 排序）。"""
    start, end = params.resolve()
    dept, proj = params.resolve_scopes()
    async with async_session() as session:
        try:
            data = await efficiency_cost_service.get_top_users(
                session, start, end, params.metric, params.cost_type, dept, proj
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class BudgetInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    month: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM；空=当月"
    )
    dimension: str = Field(default="department", pattern="^(department|project)$")
    scope_ids: list[int] = Field(default_factory=list, description="部门或项目 ID")


@mcp.tool(name="admin_efficiency_budget", annotations=READ_ONLY)
async def admin_efficiency_budget(params: BudgetInput) -> str:
    """预算总览（按维度/月份）。"""
    dept = params.scope_ids if params.dimension == "department" else None
    proj = params.scope_ids if params.dimension == "project" else None
    async with async_session() as session:
        try:
            data = await efficiency_budget_service.get_budget(
                session, params.month, dept, proj
            )
            if isinstance(data, dict):
                data["freshness"] = await efficiency_service.get_freshness(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_efficiency_budget_alerts", annotations=READ_ONLY)
async def admin_efficiency_budget_alerts(params: BudgetInput) -> str:
    """预算告警列表。"""
    dept = params.scope_ids if params.dimension == "department" else None
    proj = params.scope_ids if params.dimension == "project" else None
    async with async_session() as session:
        try:
            data = await efficiency_budget_service.get_budget_alerts(
                session, params.month, dept, proj
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class AdoptionInput(ScopeInput):
    metric: str = Field(default="dau")


@mcp.tool(name="admin_efficiency_adoption", annotations=READ_ONLY)
async def admin_efficiency_adoption(params: AdoptionInput) -> str:
    """采用分析（DAU 等指标，按维度）。"""
    start, end = params.resolve()
    dept, proj = params.resolve_scopes()
    async with async_session() as session:
        try:
            data = await efficiency_service.get_adoption(
                session, start, end, params.dimension, params.metric, dept, proj
            )
            if isinstance(data, dict):
                data["freshness"] = await efficiency_service.get_freshness(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_efficiency_health", annotations=READ_ONLY)
async def admin_efficiency_health(params: EmptyInput) -> str:
    """AI 健康度总览。"""
    async with async_session() as session:
        try:
            data = await efficiency_health_service.get_ai_health(session)
            if isinstance(data, dict):
                data["freshness"] = await efficiency_service.get_freshness(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class RefreshInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    scope: str = Field(default="all")


@mcp.tool(name="admin_refresh_efficiency", annotations=WRITE)
@audited_tool("admin_refresh_efficiency")
async def admin_refresh_efficiency(params: RefreshInput) -> str:
    """提交效能数据刷新任务。返回 {task_id,...}。"""
    try:
        data = await efficiency_service.request_refresh(params.scope)
    except (NotFoundError, ConflictError, ValidationError) as e:
        return error_text(e)
    return json_dumps(data)


class TaskIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    task_id: str = Field(..., min_length=1)


@mcp.tool(name="admin_efficiency_refresh_status", annotations=READ_ONLY)
async def admin_efficiency_refresh_status(params: TaskIdInput) -> str:
    """查询效能刷新任务状态。"""
    try:
        data = efficiency_service.get_refresh_status(params.task_id)
    except (NotFoundError, ConflictError, ValidationError) as e:
        return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_list_efficiency_reports", annotations=READ_ONLY)
async def admin_list_efficiency_reports(params: PageInput) -> str:
    """分页查询分析报告列表。"""
    async with async_session() as session:
        try:
            items, total = await efficiency_report_service.list_reports(
                session, params.page, params.page_size
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {
            "items": items,
            "total": total,
            "page": params.page,
            "page_size": params.page_size,
        }
    )


class ReportIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    report_id: int = Field(..., ge=1)


@mcp.tool(name="admin_get_efficiency_report", annotations=READ_ONLY)
async def admin_get_efficiency_report(params: ReportIdInput) -> str:
    """查询分析报告详情（含建议）。"""
    async with async_session() as session:
        try:
            data = await efficiency_report_service.get_report_detail(
                session, params.report_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class CreateReportInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    report_type: str = Field(..., pattern="^(weekly|monthly|custom)$")
    period_start: date
    period_end: date
    model_used: str | None = None
    filters: dict | None = None


@mcp.tool(name="admin_create_efficiency_report", annotations=WRITE)
@audited_tool("admin_create_efficiency_report")
async def admin_create_efficiency_report(params: CreateReportInput) -> str:
    """生成分析报告。返回新建报告详情。"""
    created_by = actor_id()
    async with async_session() as session:
        try:
            data = await efficiency_report_service.create_report(
                session,
                params.report_type,
                params.period_start,
                params.period_end,
                created_by,
                params.model_used,
                params.filters,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class UpdateSuggestionInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    suggestion_id: int = Field(..., ge=1)
    status: str = Field(..., pattern="^(pending|accepted|rejected|implemented)$")
    note: str = ""


@mcp.tool(name="admin_update_efficiency_suggestion", annotations=WRITE)
@audited_tool("admin_update_efficiency_suggestion")
async def admin_update_efficiency_suggestion(params: UpdateSuggestionInput) -> str:
    """更新报告建议状态。返回更新后建议。"""
    updated_by = actor_id()
    async with async_session() as session:
        try:
            data = await efficiency_report_service.update_suggestion_status(
                session, params.suggestion_id, params.status, params.note, updated_by
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)
