"""模型管理工具。"""

from datetime import date

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, error_text, json_dumps
from mcp_admin.server import mcp
from services import model_service


class ListModelsInput(PageInput):
    category: str | None = Field(default=None, description="按分类过滤")


class ModelIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    model_id: int = Field(..., ge=1, description="模型主键 ID")


class CreateModelInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., description="模型显示名")
    model_id: str = Field(default="", description="模型标识（如 gpt-4o），可空")
    category: str = Field(default="chat", description="分类，如 chat/embedding/rerank")
    capabilities: list[str] = Field(default_factory=list, description="能力标签")
    description: str = ""
    logo_provider_type: str | None = Field(
        default=None, description="供应商类型，用于生成图标"
    )
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    supports_vision: bool | None = None
    supports_function_calling: bool | None = None
    supports_reasoning: bool | None = None
    supports_response_schema: bool | None = None
    supports_parallel_function_calling: bool | None = None
    supports_tool_choice: bool | None = None
    litellm_provider: str | None = None
    mode: str | None = Field(
        default=None,
        description="LiteLLM mode，如 image_generation/audio_speech/audio_transcription/video_generation",
    )
    deprecation_date: date | None = Field(
        default=None, description="模型弃用日期（YYYY-MM-DD）"
    )
    registry_rpm: int | None = Field(
        default=None, ge=1, description="注册表声明的 provider 速率硬限 RPM（只读快照）"
    )
    registry_tpm: int | None = Field(
        default=None, ge=1, description="注册表声明的 provider 速率硬限 TPM（只读快照）"
    )


class UpdateModelInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    model_id: int = Field(..., ge=1)
    name: str | None = None
    model_id_str: str | None = Field(
        default=None, description="新模型标识；改名会级联同步 LiteLLM 与引用 Key"
    )
    category: str | None = None
    capabilities: list[str] | None = None
    description: str | None = None
    logo_provider_type: str | None = None
    is_active: bool | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    supports_vision: bool | None = None
    supports_function_calling: bool | None = None
    supports_reasoning: bool | None = None
    supports_response_schema: bool | None = None
    supports_parallel_function_calling: bool | None = None
    supports_tool_choice: bool | None = None
    litellm_provider: str | None = None
    mode: str | None = Field(
        default=None,
        description="LiteLLM mode，如 image_generation/audio_speech/audio_transcription/video_generation",
    )
    deprecation_date: date | None = Field(
        default=None, description="模型弃用日期（YYYY-MM-DD）"
    )
    registry_rpm: int | None = Field(
        default=None, ge=1, description="注册表声明的 provider 速率硬限 RPM（只读快照）"
    )
    registry_tpm: int | None = Field(
        default=None, ge=1, description="注册表声明的 provider 速率硬限 TPM（只读快照）"
    )


class PublishModelInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    model_id: int = Field(..., ge=1)
    is_published: bool | None = None
    visibility_type: str | None = Field(default=None, description="all|selected")
    department_ids: list[int] | None = Field(
        default=None, description="visibility_type=selected 时的部门列表"
    )
    requires_approval: bool | None = None


@mcp.tool(
    name="admin_list_models",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_list_models(params: ListModelsInput) -> str:
    """分页查询模型列表（仅活跃模型）。返回 {items,total,page,page_size}。"""
    async with async_session() as session:
        try:
            data = await model_service.list_models(
                session, params.page, params.page_size, params.category
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_get_model",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_get_model(params: ModelIdInput) -> str:
    """按 ID 查询模型详情（含部署列表）。"""
    async with async_session() as session:
        try:
            data = await model_service.get_model_by_id(session, params.model_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_create_model",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@audited_tool("admin_create_model")
async def admin_create_model(params: CreateModelInput) -> str:
    """创建模型（仅落库，不同步 LiteLLM；部署需另建）。返回新建模型详情。"""
    async with async_session() as session:
        try:
            data = await model_service.create_model(
                session,
                name=params.name,
                model_id=params.model_id,
                category=params.category,
                capabilities=params.capabilities,
                description=params.description,
                logo_provider_type=params.logo_provider_type,
                max_input_tokens=params.max_input_tokens,
                max_output_tokens=params.max_output_tokens,
                supports_vision=params.supports_vision,
                supports_function_calling=params.supports_function_calling,
                supports_reasoning=params.supports_reasoning,
                supports_response_schema=params.supports_response_schema,
                supports_parallel_function_calling=params.supports_parallel_function_calling,
                supports_tool_choice=params.supports_tool_choice,
                litellm_provider=params.litellm_provider,
                mode=params.mode,
                deprecation_date=params.deprecation_date,
                registry_rpm=params.registry_rpm,
                registry_tpm=params.registry_tpm,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_update_model",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_update_model")
async def admin_update_model(params: UpdateModelInput) -> str:
    """更新模型。改 model_id_str（改名）会级联同步 LiteLLM 与所有引用 Key。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await model_service.update_model(
                session,
                params.model_id,
                name=params.name,
                model_id_str=params.model_id_str,
                category=params.category,
                capabilities=params.capabilities,
                description=params.description,
                logo_provider_type=params.logo_provider_type,
                is_active=params.is_active,
                max_input_tokens=params.max_input_tokens,
                max_output_tokens=params.max_output_tokens,
                supports_vision=params.supports_vision,
                supports_function_calling=params.supports_function_calling,
                supports_reasoning=params.supports_reasoning,
                supports_response_schema=params.supports_response_schema,
                supports_parallel_function_calling=params.supports_parallel_function_calling,
                supports_tool_choice=params.supports_tool_choice,
                litellm_provider=params.litellm_provider,
                mode=params.mode,
                deprecation_date=params.deprecation_date,
                registry_rpm=params.registry_rpm,
                registry_tpm=params.registry_tpm,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_delete_model",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_delete_model")
async def admin_delete_model(params: ModelIdInput) -> str:
    """删除模型（LiteLLM 侧禁用而非物理删除）。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await model_service.delete_model(session, params.model_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "model_id": params.model_id})


@mcp.tool(
    name="admin_publish_model",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_publish_model")
async def admin_publish_model(params: PublishModelInput) -> str:
    """更新模型发布状态与可见性。发布变更会广播到所有主 Key。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await model_service.update_model_publish(
                session,
                params.model_id,
                is_published=params.is_published,
                visibility_type=params.visibility_type,
                department_ids=params.department_ids,
                requires_approval=params.requires_approval,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)
