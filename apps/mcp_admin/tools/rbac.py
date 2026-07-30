"""RBAC 工具（M4）：角色 / 权限 + 用户归属（角色/部门/项目）。"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import error_text, json_dumps
from mcp_admin.server import mcp
from services import role_service, user_service

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


# ---------- 角色 / 权限 ----------


class CreateRoleInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=100)
    description: str = ""


class RoleIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    role_id: int = Field(..., ge=1)


class UpdateRoleInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    role_id: int = Field(..., ge=1)
    display_name: str | None = None
    description: str | None = None


class RolePermissionsInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    role_id: int = Field(..., ge=1)
    permission_ids: list[int] = Field(default_factory=list)


@mcp.tool(name="admin_list_roles", annotations=READ_ONLY)
async def admin_list_roles(params: EmptyInput) -> str:
    """列出全部角色。"""
    async with async_session() as session:
        try:
            data = await role_service.list_roles(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_role", annotations=WRITE)
@audited_tool("admin_create_role")
async def admin_create_role(params: CreateRoleInput) -> str:
    """创建角色。返回新建详情。"""
    async with async_session() as session:
        try:
            data = await role_service.create_role(
                session, params.name, params.display_name, params.description
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_role", annotations=WRITE)
@audited_tool("admin_update_role")
async def admin_update_role(params: UpdateRoleInput) -> str:
    """更新角色（display_name / description）。"""
    async with async_session() as session:
        try:
            data = await role_service.update_role(
                session, params.role_id, params.display_name, params.description
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_role", annotations=DELETE)
@audited_tool("admin_delete_role")
async def admin_delete_role(params: RoleIdInput) -> str:
    """删除角色。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await role_service.delete_role(session, params.role_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "role_id": params.role_id})


@mcp.tool(name="admin_update_role_permissions", annotations=WRITE)
@audited_tool("admin_update_role_permissions")
async def admin_update_role_permissions(params: RolePermissionsInput) -> str:
    """更新角色权限（整体覆盖）。返回更新后角色。"""
    async with async_session() as session:
        try:
            data = await role_service.update_role_permissions(
                session, params.role_id, params.permission_ids
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_list_permissions", annotations=READ_ONLY)
async def admin_list_permissions(params: EmptyInput) -> str:
    """列出全部可分配权限。"""
    async with async_session() as session:
        try:
            data = await role_service.list_permissions(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


# ---------- 用户归属 ----------


class UpdateUserRolesInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    user_id: int = Field(..., ge=1)
    role_ids: list[int] = Field(default_factory=list, description="整体覆盖")


class UpdateUserDepartmentsInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    user_id: int = Field(..., ge=1)
    department_ids: list[int] = Field(default_factory=list, description="整体覆盖")


class UpdateUserProjectsInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    user_id: int = Field(..., ge=1)
    project_ids: list[int] = Field(default_factory=list, description="整体覆盖")


@mcp.tool(name="admin_update_user_roles", annotations=WRITE)
@audited_tool("admin_update_user_roles")
async def admin_update_user_roles(params: UpdateUserRolesInput) -> str:
    """更新用户角色（整体覆盖）。返回 {updated:true}。"""
    async with async_session() as session:
        try:
            await user_service.update_user_roles(
                session, params.user_id, params.role_ids
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {"updated": True, "user_id": params.user_id, "role_ids": params.role_ids}
    )


@mcp.tool(name="admin_update_user_departments", annotations=WRITE)
@audited_tool("admin_update_user_departments")
async def admin_update_user_departments(params: UpdateUserDepartmentsInput) -> str:
    """更新用户部门归属（整体覆盖）。返回 {updated:true}。"""
    async with async_session() as session:
        try:
            await user_service.update_user_departments(
                session, params.user_id, params.department_ids
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {
            "updated": True,
            "user_id": params.user_id,
            "department_ids": params.department_ids,
        }
    )


@mcp.tool(name="admin_update_user_projects", annotations=WRITE)
@audited_tool("admin_update_user_projects")
async def admin_update_user_projects(params: UpdateUserProjectsInput) -> str:
    """更新用户项目归属（整体覆盖）。返回 {updated:true}。"""
    async with async_session() as session:
        try:
            await user_service.update_user_projects(
                session, params.user_id, params.project_ids
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {
            "updated": True,
            "user_id": params.user_id,
            "project_ids": params.project_ids,
        }
    )
