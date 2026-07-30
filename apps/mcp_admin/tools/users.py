"""用户管理工具。"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, error_text, json_dumps
from mcp_admin.server import mcp
from services import user_service


class ListUsersInput(PageInput):
    keyword: str = Field(default="", description="按用户名/邮箱模糊搜索")


class GetAndDeleteInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    user_id: int = Field(..., description="用户 ID", ge=1)


class CreateUserInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    username: str = Field(..., min_length=2, max_length=64, description="用户名")
    email: str = Field(..., description="邮箱")
    password: str = Field(..., min_length=6, max_length=128, description="初始密码")
    phone: str = Field(default="", description="手机号")
    display_name: str = Field(default="", description="显示名")
    position: str = Field(default="", description="职位")
    avatar: str = Field(default="", description="头像 URL")
    is_active: bool = Field(default=True, description="是否启用")


class UpdateUserInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    user_id: int = Field(..., ge=1)
    email: str | None = None
    phone: str | None = None
    display_name: str | None = None
    position: str | None = None
    avatar: str | None = None
    is_active: bool | None = None


class ResetPasswordInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    user_id: int = Field(..., ge=1)
    new_password: str = Field(..., min_length=6, max_length=128)


@mcp.tool(
    name="admin_list_users",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_list_users(params: ListUsersInput) -> str:
    """分页查询平台用户列表。

    返回 JSON：{items:[{id,username,email,...}], total, page, page_size}。
    """
    async with async_session() as session:
        try:
            data = await user_service.list_users(
                session, params.page, params.page_size, params.keyword
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_get_user",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_get_user(params: GetAndDeleteInput) -> str:
    """按 ID 查询单个用户详情。"""
    async with async_session() as session:
        try:
            data = await user_service.get_user_by_id(session, params.user_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_create_user",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@audited_tool("admin_create_user")
async def admin_create_user(params: CreateUserInput) -> str:
    """创建用户。会同步在 LiteLLM 建账号与个人主 Key（可能较慢/失败）。返回新建用户详情。"""
    async with async_session() as session:
        try:
            data = await user_service.create_user(
                session,
                params.username,
                params.email,
                params.password,
                params.phone,
                params.display_name,
                params.position,
                params.avatar,
                params.is_active,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_update_user",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_update_user")
async def admin_update_user(params: UpdateUserInput) -> str:
    """更新用户资料。只传需修改的字段；切换 is_active 会同步名下 Key 到 LiteLLM。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await user_service.update_user(
                session,
                params.user_id,
                params.email,
                params.phone,
                params.display_name,
                params.position,
                params.avatar,
                params.is_active,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_delete_user",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@audited_tool("admin_delete_user")
async def admin_delete_user(params: GetAndDeleteInput) -> str:
    """删除用户。有名下 ApiKey/AiKey/McpServer/Skill/Agent 时拒绝（RESTRICT）。返回 {deleted:true} 或错误文本。"""
    async with async_session() as session:
        try:
            await user_service.delete_user(session, params.user_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "user_id": params.user_id})


@mcp.tool(
    name="admin_reset_user_password",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@audited_tool("admin_reset_user_password")
async def admin_reset_user_password(params: ResetPasswordInput) -> str:
    """重置用户密码。返回 {reset:true}。"""
    async with async_session() as session:
        try:
            await user_service.reset_password(
                session, params.user_id, params.new_password
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"reset": True, "user_id": params.user_id})
