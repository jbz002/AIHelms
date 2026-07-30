"""模型纳管深化工具（M3）：部署/访问组/路由/可见性/Anthropic 重同步。"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import error_text, json_dumps
from mcp_admin.server import mcp
from services import model_service

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


# ---------- 部署 ----------


class CreateDeploymentInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    model_id: int = Field(..., ge=1)
    litellm_params: dict = Field(..., description="LiteLLM 部署参数")
    credential_id: int | None = Field(default=None, ge=1)
    deploy_name: str = ""
    billing_type: str = "token"
    cost_per_call: float | None = Field(default=None, ge=0)
    monthly_call_quota: int | None = Field(default=None, ge=0)
    model_info: dict | None = None
    model_id_str: str | None = None


class UpdateDeploymentInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    deployment_id: int = Field(..., ge=1)
    litellm_params: dict | None = None
    credential_id: int | None = Field(default=None, ge=1)
    deploy_name: str | None = None
    billing_type: str | None = None
    cost_per_call: float | None = Field(default=None, ge=0)
    monthly_call_quota: int | None = Field(default=None, ge=0)
    model_info: dict | None = None
    is_active: bool | None = None
    model_id_str: str | None = None


class DeploymentIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    deployment_id: int = Field(..., ge=1)


@mcp.tool(name="admin_create_deployment", annotations=WRITE)
@audited_tool("admin_create_deployment")
async def admin_create_deployment(params: CreateDeploymentInput) -> str:
    """创建模型部署（同步到 LiteLLM）。返回新建部署详情。"""
    async with async_session() as session:
        try:
            data = await model_service.create_deployment(
                session,
                params.model_id,
                params.litellm_params,
                params.credential_id,
                params.deploy_name,
                params.billing_type,
                params.cost_per_call,
                params.monthly_call_quota,
                params.model_info,
                params.model_id_str,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_deployment", annotations=WRITE)
@audited_tool("admin_update_deployment")
async def admin_update_deployment(params: UpdateDeploymentInput) -> str:
    """更新模型部署（同步到 LiteLLM）。"""
    async with async_session() as session:
        try:
            data = await model_service.update_deployment(
                session,
                params.deployment_id,
                params.litellm_params,
                params.credential_id,
                params.deploy_name,
                params.billing_type,
                params.cost_per_call,
                params.monthly_call_quota,
                params.model_info,
                params.is_active,
                params.model_id_str,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_deployment", annotations=DELETE)
@audited_tool("admin_delete_deployment")
async def admin_delete_deployment(params: DeploymentIdInput) -> str:
    """删除模型部署（LiteLLM 侧移除）。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await model_service.delete_deployment(session, params.deployment_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "deployment_id": params.deployment_id})


# ---------- 访问组 ----------


class GroupIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    group_id: int = Field(..., ge=1)


class CreateAccessGroupInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    group_name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    model_ids: list[str] | None = None


class UpdateAccessGroupInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    group_id: int = Field(..., ge=1)
    group_name: str | None = None
    description: str | None = None
    model_ids: list[str] | None = None
    is_active: bool | None = None


@mcp.tool(name="admin_list_access_groups", annotations=READ_ONLY)
async def admin_list_access_groups(params: EmptyInput) -> str:
    """列出全部访问组。"""
    async with async_session() as session:
        try:
            data = await model_service.list_access_groups(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_access_group", annotations=WRITE)
@audited_tool("admin_create_access_group")
async def admin_create_access_group(params: CreateAccessGroupInput) -> str:
    """创建访问组。返回新建详情。"""
    async with async_session() as session:
        try:
            data = await model_service.create_access_group(
                session, params.group_name, params.description, params.model_ids
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_access_group", annotations=WRITE)
@audited_tool("admin_update_access_group")
async def admin_update_access_group(params: UpdateAccessGroupInput) -> str:
    """更新访问组。"""
    async with async_session() as session:
        try:
            data = await model_service.update_access_group(
                session,
                params.group_id,
                params.group_name,
                params.description,
                params.model_ids,
                params.is_active,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_access_group", annotations=DELETE)
@audited_tool("admin_delete_access_group")
async def admin_delete_access_group(params: GroupIdInput) -> str:
    """删除访问组。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await model_service.delete_access_group(session, params.group_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "group_id": params.group_id})


# ---------- 路由 / 可见性 / Anthropic 重同步 ----------


class UpdateRouterSettingsInput(BaseModel):
    routing_strategy: str | None = None
    fallbacks: list | None = None
    allowed_fails: int | None = Field(default=None, ge=0)
    cooldown_time: int | None = Field(default=None, ge=0)
    num_retries: int | None = Field(default=None, ge=0)
    timeout: int | None = Field(default=None, ge=0)
    config: dict | None = None


class ModelIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    model_id: int = Field(..., ge=1)


@mcp.tool(name="admin_get_router_settings", annotations=READ_ONLY)
async def admin_get_router_settings(params: EmptyInput) -> str:
    """查询 LiteLLM 路由设置。"""
    async with async_session() as session:
        try:
            data = await model_service.get_router_settings(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_router_settings", annotations=WRITE)
@audited_tool("admin_update_router_settings")
async def admin_update_router_settings(params: UpdateRouterSettingsInput) -> str:
    """更新 LiteLLM 路由设置（策略/fallback/重试/超时）。"""
    async with async_session() as session:
        try:
            data = await model_service.update_router_settings(
                session,
                params.routing_strategy,
                params.fallbacks,
                params.allowed_fails,
                params.cooldown_time,
                params.num_retries,
                params.timeout,
                params.config,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_model_visibility", annotations=READ_ONLY)
async def admin_get_model_visibility(params: ModelIdInput) -> str:
    """查询模型可见性（哪些部门/Key 可见）。"""
    async with async_session() as session:
        try:
            data = await model_service.get_model_visibility(session, params.model_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_resync_anthropic_deployments", annotations=WRITE)
@audited_tool("admin_resync_anthropic_deployments")
async def admin_resync_anthropic_deployments(params: EmptyInput) -> str:
    """重同步 Anthropic 部署（从供应商侧拉取最新模型列表）。"""
    async with async_session() as session:
        try:
            data = await model_service.resync_anthropic_deployments(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)
