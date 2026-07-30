"""AI 身份 Key 管理工具。"""

from decimal import Decimal

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, actor_id, error_text, json_dumps
from mcp_admin.server import mcp
from services import ai_key_service


class ListKeysInput(PageInput):
    owner_type: str | None = Field(
        default=None, description="过滤归属：user|department|project"
    )
    owner_id: int | None = Field(default=None, description="归属 ID")
    key_type: str | None = Field(
        default=None, description="Key 类型，如 personal_scene"
    )


class KeyIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    key_id: int = Field(..., ge=1)


class CreateSceneKeyInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., description="Key 名称")
    key_type: str = Field(..., description="personal_scene|dept_scene|project_scene")
    owner_type: str = Field(..., description="user|department|project")
    owner_id: int = Field(..., ge=1, description="归属 ID")
    description: str = ""
    models: list[str] = Field(default_factory=list, description="授权模型 ID 列表")
    mcps: list[int] = Field(default_factory=list, description="授权 MCP Server ID 列表")
    skills: list[int] = Field(default_factory=list, description="授权 Skill ID 列表")
    budget_limit: Decimal | None = Field(default=None, description="预算上限")
    budget_hard_limit: bool = Field(default=False, description="超预算是否硬阻断")
    budget_duration: str = Field(default="30d", description="预算周期：1d|7d|30d")


class UpdateKeyInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    key_id: int = Field(..., ge=1)
    name: str | None = None
    description: str | None = None
    models: list[str] | None = None
    mcps: list[int] | None = None
    skills: list[int] | None = None
    budget_limit: Decimal | None = None
    budget_hard_limit: bool | None = None
    budget_duration: str | None = None


@mcp.tool(
    name="admin_list_keys",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_list_keys(params: ListKeysInput) -> str:
    """分页查询 AI 身份 Key 列表（含主 Key 与场景 Key）。可按归属/类型过滤。返回 {items,total,page,page_size}。"""
    async with async_session() as session:
        try:
            data = await ai_key_service.list_keys(
                session,
                params.page,
                params.page_size,
                params.owner_type,
                params.owner_id,
                params.key_type,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_get_key",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_get_key(params: KeyIdInput) -> str:
    """按 ID 查询单个 AI Key 详情。"""
    async with async_session() as session:
        try:
            data = await ai_key_service.get_key_by_id(session, params.key_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_create_scene_key",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@audited_tool("admin_create_scene_key")
async def admin_create_scene_key(params: CreateSceneKeyInput) -> str:
    """创建场景 Key（personal_scene/dept_scene/project_scene）。主 Key 由平台自动创建，不可手动建。

    所有写操作会同步到 LiteLLM。返回含 key_value（仅本次返回，请妥善保存）。
    """
    created_by = actor_id()
    async with async_session() as session:
        try:
            data = await ai_key_service.create_key(
                session,
                name=params.name,
                key_type=params.key_type,
                owner_type=params.owner_type,
                owner_id=params.owner_id,
                created_by=created_by,
                description=params.description,
                models=params.models,
                mcps=params.mcps,
                skills=params.skills,
                budget_limit=params.budget_limit,
                budget_hard_limit=params.budget_hard_limit,
                budget_duration=params.budget_duration,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_update_key",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_update_key")
async def admin_update_key(params: UpdateKeyInput) -> str:
    """更新 AI Key。只传需修改字段；变更会同步到 LiteLLM。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await ai_key_service.update_key(
                session,
                params.key_id,
                name=params.name,
                description=params.description,
                models=params.models,
                mcps=params.mcps,
                skills=params.skills,
                budget_limit=params.budget_limit,
                budget_hard_limit=params.budget_hard_limit,
                budget_duration=params.budget_duration,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_toggle_key",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@audited_tool("admin_toggle_key")
async def admin_toggle_key(params: KeyIdInput) -> str:
    """切换 AI Key 启用/禁用（翻转状态，非幂等）。同步到 LiteLLM。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await ai_key_service.toggle_key(session, params.key_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_delete_key",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_delete_key")
async def admin_delete_key(params: KeyIdInput) -> str:
    """删除 AI Key（同步删 LiteLLM 侧）。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await ai_key_service.delete_key(session, params.key_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "key_id": params.key_id})


# ---------- M3 补强：批量 / 资源 / 限额 / 身份 / 公共资源 ----------


BATCH_MAX = 100


class BatchCreateKeysInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    user_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=BATCH_MAX,
        description=f"目标用户 ID 列表，单次≤{BATCH_MAX}（Q18）",
    )
    key_type: str = Field(..., description="personal_scene|dept_scene|project_scene")
    name_template: str = Field(..., description="Key 名称模板")
    description: str = ""
    models: list[str] | None = None
    mcps: list[int] | None = None
    skills: list[int] | None = None
    agents: list[int] | None = None
    budget_limit: Decimal | None = None
    budget_hard_limit: bool = False
    budget_duration: str | None = "30d"


@mcp.tool(
    name="admin_batch_create_keys",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@audited_tool("admin_batch_create_keys")
async def admin_batch_create_keys(params: BatchCreateKeysInput) -> str:
    """批量为多个用户创建场景 Key（单次≤100，Q18）。

    仅暴露核心参数；高级预算细分/限流参数走 Web UI。返回新建 Key 列表。
    """
    created_by = actor_id()
    async with async_session() as session:
        try:
            data = await ai_key_service.batch_create_keys(
                session,
                params.user_ids,
                params.key_type,
                params.name_template,
                created_by,
                params.description,
                params.models,
                params.mcps,
                params.skills,
                params.agents,
                params.budget_limit,
                params.budget_hard_limit,
                params.budget_duration,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"created": data, "count": len(data)})


class UpdateKeyResourcesInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    key_id: int = Field(..., ge=1)
    models: list[str] | None = None
    mcps: list[int] | None = None
    skills: list[int] | None = None
    agents: list[int] | None = None


@mcp.tool(
    name="admin_update_key_resources",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_update_key_resources")
async def admin_update_key_resources(params: UpdateKeyResourcesInput) -> str:
    """更新 Key 绑定的资源（模型/MCP/Skill/Agent，None 字段不变）。返回 {updated:true}。"""
    async with async_session() as session:
        try:
            await ai_key_service.update_key_resources(
                session,
                params.key_id,
                params.models,
                params.mcps,
                params.skills,
                params.agents,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"updated": True, "key_id": params.key_id})


@mcp.tool(
    name="admin_get_model_limits",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_get_model_limits(params: KeyIdInput) -> str:
    """查询 Key 的模型限额列表。"""
    async with async_session() as session:
        try:
            data = await ai_key_service.get_model_limits(session, params.key_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class SetModelLimitsInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    key_id: int = Field(..., ge=1)
    limits: list[dict] = Field(..., description="模型限额列表")


@mcp.tool(
    name="admin_set_model_limits",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@audited_tool("admin_set_model_limits")
async def admin_set_model_limits(params: SetModelLimitsInput) -> str:
    """设置 Key 的模型限额（整体覆盖）。返回限额列表。"""
    async with async_session() as session:
        try:
            data = await ai_key_service.set_model_limits(
                session, params.key_id, params.limits
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class KeyModelInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    key_id: int = Field(..., ge=1)
    model_id: int = Field(..., ge=1, description="模型限额记录的 model_id")


@mcp.tool(
    name="admin_delete_model_limit",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@audited_tool("admin_delete_model_limit")
async def admin_delete_model_limit(params: KeyModelInput) -> str:
    """删除 Key 的单个模型限额。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await ai_key_service.delete_model_limit(
                session, params.key_id, params.model_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {"deleted": True, "key_id": params.key_id, "model_id": params.model_id}
    )


class ListIdentityInput(PageInput):
    tab: str = Field(..., description="视图 tab（如 user|department|project）")
    keyword: str | None = None


@mcp.tool(
    name="admin_list_identity",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_list_identity(params: ListIdentityInput) -> str:
    """分页查询 AI 身份视图（按 tab 切换 user/department/project 维度）。"""
    async with async_session() as session:
        try:
            data = await ai_key_service.list_identity(
                session,
                params.tab,
                params.page,
                params.page_size,
                params.keyword,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


class PublicResourceInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    resource_type: str = Field(..., description="model|mcp|skill|agent")
    resource_id: str = Field(..., description="资源 ID（model 传标识串，其余传数字串）")


@mcp.tool(
    name="admin_sync_public_resources",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_sync_public_resources")
async def admin_sync_public_resources(params: PublicResourceInput) -> str:
    """把公共资源同步到所有 Key。返回 {synced: 影响Key数}。"""
    async with async_session() as session:
        try:
            count = await ai_key_service.sync_public_resource_to_all_keys(
                session, params.resource_type, params.resource_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {
            "synced": count,
            "resource_type": params.resource_type,
            "resource_id": params.resource_id,
        }
    )


@mcp.tool(
    name="admin_remove_public_resources",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_remove_public_resources")
async def admin_remove_public_resources(params: PublicResourceInput) -> str:
    """从所有 Key 移除某公共资源。返回 {removed: 影响Key数}。"""
    async with async_session() as session:
        try:
            count = await ai_key_service.remove_public_resource_from_all_keys(
                session, params.resource_type, params.resource_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {
            "removed": count,
            "resource_type": params.resource_type,
            "resource_id": params.resource_id,
        }
    )
