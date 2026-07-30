"""平台运维工具（M7）上：平台 API Key / CLI 令牌 / 平台设置。"""

from datetime import datetime

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, actor, actor_id, error_text, json_dumps
from mcp_admin.server import mcp
from services import api_key_service, cli_token_service, platform_settings_service

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


def _current_user() -> dict:
    a = actor()
    return {"id": a["user_id"], "username": a["username"], "is_admin": True}


# ---------- 平台 API Key ----------


class ListApiKeysInput(PageInput):
    keyword: str = ""


class ApiKeyIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    key_id: int = Field(..., ge=1)


class CreateApiKeyInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    expires_at: datetime | None = None


class UpdateApiKeyInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    key_id: int = Field(..., ge=1)
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    expires_at: datetime | None = None
    expires_at_provided: bool = Field(
        default=False, description="true 时才写入 expires_at（区分不改 vs 清空）"
    )


@mcp.tool(name="admin_list_api_keys", annotations=READ_ONLY)
async def admin_list_api_keys(params: ListApiKeysInput) -> str:
    """分页查询平台 API Key 列表（区别于 AI Key）。"""
    async with async_session() as session:
        try:
            data = await api_key_service.list_api_keys(
                session, params.page, params.page_size, params.keyword
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_api_key", annotations=READ_ONLY)
async def admin_get_api_key(params: ApiKeyIdInput) -> str:
    """查询平台 API Key 详情。"""
    async with async_session() as session:
        try:
            data = await api_key_service.get_api_key(session, params.key_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_api_key", annotations=WRITE)
@audited_tool("admin_create_api_key")
async def admin_create_api_key(params: CreateApiKeyInput) -> str:
    """创建平台 API Key。返回详情（含 key_value 明文，仅本次返回）。"""
    created_by = actor_id()
    async with async_session() as session:
        try:
            data, key_value = await api_key_service.create_api_key(
                session,
                params.name,
                params.description,
                params.expires_at,
                created_by,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({**data, "key_value": key_value})


@mcp.tool(name="admin_update_api_key", annotations=WRITE)
@audited_tool("admin_update_api_key")
async def admin_update_api_key(params: UpdateApiKeyInput) -> str:
    """更新平台 API Key。"""
    async with async_session() as session:
        try:
            data = await api_key_service.update_api_key(
                session,
                params.key_id,
                params.name,
                params.description,
                params.is_active,
                params.expires_at,
                params.expires_at_provided,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_api_key", annotations=DELETE)
@audited_tool("admin_delete_api_key")
async def admin_delete_api_key(params: ApiKeyIdInput) -> str:
    """删除平台 API Key。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await api_key_service.delete_api_key(session, params.key_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "key_id": params.key_id})


# ---------- CLI 令牌 ----------


class ListCliTokensInput(PageInput):
    owner_id: int | None = Field(default=None, ge=1)


class TokenIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    token_id: int = Field(..., ge=1)


class CreateCliTokenInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    scopes: list[str] = Field(default_factory=list)
    owner_id: int = Field(..., ge=1)
    owner_type: str = "user"
    expires_at: datetime | None = None


class UpdateCliTokenInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    token_id: int = Field(..., ge=1)
    name: str | None = None
    description: str | None = None
    scopes: list[str] | None = None
    is_active: bool | None = None


@mcp.tool(name="admin_list_cli_tokens", annotations=READ_ONLY)
async def admin_list_cli_tokens(params: ListCliTokensInput) -> str:
    """分页查询 CLI 令牌列表。"""
    async with async_session() as session:
        try:
            data = await cli_token_service.list_tokens(
                session, params.page, params.page_size, params.owner_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_cli_token", annotations=READ_ONLY)
async def admin_get_cli_token(params: TokenIdInput) -> str:
    """查询 CLI 令牌详情。"""
    async with async_session() as session:
        try:
            data = await cli_token_service.get_token(session, params.token_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_cli_token", annotations=WRITE)
@audited_tool("admin_create_cli_token")
async def admin_create_cli_token(params: CreateCliTokenInput) -> str:
    """创建 CLI 令牌。返回详情（含 token 明文，仅本次返回）。"""
    created_by = actor_id()
    async with async_session() as session:
        try:
            data, token_value = await cli_token_service.create_token(
                session,
                name=params.name,
                description=params.description,
                scopes=params.scopes,
                owner_id=params.owner_id,
                owner_type=params.owner_type,
                expires_at=params.expires_at,
                created_by=created_by,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({**data, "token_value": token_value})


@mcp.tool(name="admin_update_cli_token", annotations=WRITE)
@audited_tool("admin_update_cli_token")
async def admin_update_cli_token(params: UpdateCliTokenInput) -> str:
    """更新 CLI 令牌。"""
    async with async_session() as session:
        try:
            data = await cli_token_service.update_token(
                session,
                params.token_id,
                name=params.name,
                description=params.description,
                scopes=params.scopes,
                is_active=params.is_active,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_revoke_cli_token", annotations=DELETE)
@audited_tool("admin_revoke_cli_token")
async def admin_revoke_cli_token(params: TokenIdInput) -> str:
    """吊销 CLI 令牌。返回 {revoked:true}。"""
    async with async_session() as session:
        try:
            await cli_token_service.revoke_token(session, params.token_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"revoked": True, "token_id": params.token_id})


# ---------- 平台设置 ----------


class UpdateDefaultModelInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    model_id: int | None = Field(
        default=None, ge=1, description="默认模型主键；None=清空"
    )


@mcp.tool(name="admin_get_platform_settings", annotations=READ_ONLY)
async def admin_get_platform_settings(params: EmptyInput) -> str:
    """查询平台设置（默认模型等）。"""
    async with async_session() as session:
        try:
            data = await platform_settings_service.get_settings(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_default_model", annotations=WRITE)
@audited_tool("admin_update_default_model")
async def admin_update_default_model(params: UpdateDefaultModelInput) -> str:
    """更新平台默认模型。"""
    cu = _current_user()
    async with async_session() as session:
        try:
            data = await platform_settings_service.update_default_model(
                session, params.model_id, cu
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)
