"""AI 身份 Key 管理工具。"""

from decimal import Decimal

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
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
async def admin_delete_key(params: KeyIdInput) -> str:
    """删除 AI Key（同步删 LiteLLM 侧）。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await ai_key_service.delete_key(session, params.key_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "key_id": params.key_id})
