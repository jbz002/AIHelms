"""凭证管理工具（M3）：供应商凭证 CRUD。credential_values 敏感，审计自动脱敏。"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, error_text, json_dumps
from mcp_admin.server import mcp
from services import credential_service

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


class ProviderFilterInput(PageInput):
    provider_id: int | None = Field(default=None, ge=1)


class CredentialIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    credential_id: int = Field(..., ge=1)


class CreateCredentialInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    credential_name: str = Field(..., min_length=1, max_length=100)
    credential_values: dict = Field(..., description="凭证键值（敏感，加密落库）")
    provider_id: int = Field(..., ge=1)
    credential_info: dict | None = None


class UpdateCredentialInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    credential_id: int = Field(..., ge=1)
    credential_values: dict | None = None
    provider_id: int | None = Field(default=None, ge=1)
    credential_info: dict | None = None
    is_active: bool | None = None


@mcp.tool(name="admin_list_credentials", annotations=READ_ONLY)
async def admin_list_credentials(params: ProviderFilterInput) -> str:
    """分页查询凭证列表（credential_values 脱敏返回）。"""
    async with async_session() as session:
        try:
            data = await credential_service.list_credentials(
                session, params.page, params.page_size, params.provider_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_credential", annotations=READ_ONLY)
async def admin_get_credential(params: CredentialIdInput) -> str:
    """按 ID 查询凭证详情。"""
    async with async_session() as session:
        try:
            data = await credential_service.get_credential_by_id(
                session, params.credential_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_credential", annotations=WRITE)
@audited_tool("admin_create_credential")
async def admin_create_credential(params: CreateCredentialInput) -> str:
    """创建供应商凭证（敏感值加密落库）。返回新建详情。"""
    async with async_session() as session:
        try:
            data = await credential_service.create_credential(
                session,
                params.credential_name,
                params.credential_values,
                params.provider_id,
                params.credential_info,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_credential", annotations=WRITE)
@audited_tool("admin_update_credential")
async def admin_update_credential(params: UpdateCredentialInput) -> str:
    """更新凭证。只传需修改字段。"""
    async with async_session() as session:
        try:
            data = await credential_service.update_credential(
                session,
                params.credential_id,
                params.credential_values,
                params.provider_id,
                params.credential_info,
                params.is_active,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_credential", annotations=DELETE)
@audited_tool("admin_delete_credential")
async def admin_delete_credential(params: CredentialIdInput) -> str:
    """删除凭证。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await credential_service.delete_credential(session, params.credential_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "credential_id": params.credential_id})
