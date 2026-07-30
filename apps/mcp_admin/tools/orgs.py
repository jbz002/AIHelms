"""组织治理工具（M4）：部门 + 项目。

注：Q14 决议「部门只读映射 AI Hub，本地部门 CRUD 停用」在 service 层未落地，
department_service 写方法全保留可执行；本模块按 service 现状暴露（遵平台能力原样原则，
不隐藏），冲突见规划 §8 M4 与 README 遗留问题 Q19。
"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, error_text, json_dumps
from mcp_admin.server import mcp
from services import department_service, project_service

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


# ---------- 部门 ----------


class DeptIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    dept_id: int = Field(..., ge=1)


class CreateDeptInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=100)
    parent_id: int | None = Field(default=None, ge=1)
    description: str = ""


class UpdateDeptInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    dept_id: int = Field(..., ge=1)
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class DeptMemberInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    dept_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)


class DeptManagersInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    dept_id: int = Field(..., ge=1)
    manager_user_ids: list[int] = Field(default_factory=list)


@mcp.tool(name="admin_get_department_tree", annotations=READ_ONLY)
async def admin_get_department_tree(params: EmptyInput) -> str:
    """查询部门树（含层级）。"""
    async with async_session() as session:
        try:
            data = await department_service.get_department_tree(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_department", annotations=READ_ONLY)
async def admin_get_department(params: DeptIdInput) -> str:
    """查询部门详情。"""
    async with async_session() as session:
        try:
            data = await department_service.get_department_by_id(
                session, params.dept_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_department", annotations=WRITE)
@audited_tool("admin_create_department")
async def admin_create_department(params: CreateDeptInput) -> str:
    """创建部门。返回新建详情。"""
    async with async_session() as session:
        try:
            data = await department_service.create_department(
                session, params.name, params.parent_id, params.description
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_department", annotations=WRITE)
@audited_tool("admin_update_department")
async def admin_update_department(params: UpdateDeptInput) -> str:
    """更新部门。只传需修改字段。"""
    async with async_session() as session:
        try:
            data = await department_service.update_department(
                session,
                params.dept_id,
                params.name,
                params.description,
                params.sort_order,
                params.is_active,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_department", annotations=DELETE)
@audited_tool("admin_delete_department")
async def admin_delete_department(params: DeptIdInput) -> str:
    """删除部门（有子部门/成员时拒绝）。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await department_service.delete_department(session, params.dept_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "dept_id": params.dept_id})


@mcp.tool(name="admin_list_department_members", annotations=READ_ONLY)
async def admin_list_department_members(params: DeptIdInput) -> str:
    """列出部门成员。"""
    async with async_session() as session:
        try:
            data = await department_service.get_department_members(
                session, params.dept_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_add_department_member", annotations=WRITE)
@audited_tool("admin_add_department_member")
async def admin_add_department_member(params: DeptMemberInput) -> str:
    """添加部门成员。返回 {added:true}。"""
    async with async_session() as session:
        try:
            await department_service.add_department_member(
                session, params.dept_id, params.user_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {"added": True, "dept_id": params.dept_id, "user_id": params.user_id}
    )


@mcp.tool(name="admin_remove_department_member", annotations=DELETE)
@audited_tool("admin_remove_department_member")
async def admin_remove_department_member(params: DeptMemberInput) -> str:
    """移除部门成员。返回 {removed:true}。"""
    async with async_session() as session:
        try:
            await department_service.remove_department_member(
                session, params.dept_id, params.user_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {"removed": True, "dept_id": params.dept_id, "user_id": params.user_id}
    )


@mcp.tool(name="admin_update_department_managers", annotations=WRITE)
@audited_tool("admin_update_department_managers")
async def admin_update_department_managers(params: DeptManagersInput) -> str:
    """更新部门主管（整体覆盖）。返回 {updated:true}。"""
    async with async_session() as session:
        try:
            await department_service.update_department_managers(
                session, params.dept_id, params.manager_user_ids
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {
            "updated": True,
            "dept_id": params.dept_id,
            "manager_user_ids": params.manager_user_ids,
        }
    )


# ---------- 项目 ----------


class ListProjectsInput(PageInput):
    keyword: str = ""


class ProjectIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    project_id: int = Field(..., ge=1)


class CreateProjectInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""


class UpdateProjectInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    project_id: int = Field(..., ge=1)
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class ProjectMemberInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    project_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)


@mcp.tool(name="admin_list_projects", annotations=READ_ONLY)
async def admin_list_projects(params: ListProjectsInput) -> str:
    """分页查询项目列表。"""
    async with async_session() as session:
        try:
            data = await project_service.list_projects(
                session, params.page, params.page_size, params.keyword
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_get_project", annotations=READ_ONLY)
async def admin_get_project(params: ProjectIdInput) -> str:
    """查询项目详情。"""
    async with async_session() as session:
        try:
            data = await project_service.get_project_by_id(session, params.project_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_project", annotations=WRITE)
@audited_tool("admin_create_project")
async def admin_create_project(params: CreateProjectInput) -> str:
    """创建项目。返回新建详情。"""
    async with async_session() as session:
        try:
            data = await project_service.create_project(
                session, params.name, params.description
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_update_project", annotations=WRITE)
@audited_tool("admin_update_project")
async def admin_update_project(params: UpdateProjectInput) -> str:
    """更新项目。"""
    async with async_session() as session:
        try:
            data = await project_service.update_project(
                session,
                params.project_id,
                params.name,
                params.description,
                params.is_active,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_project", annotations=DELETE)
@audited_tool("admin_delete_project")
async def admin_delete_project(params: ProjectIdInput) -> str:
    """删除项目。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await project_service.delete_project(session, params.project_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "project_id": params.project_id})


@mcp.tool(name="admin_list_project_members", annotations=READ_ONLY)
async def admin_list_project_members(params: ProjectIdInput) -> str:
    """列出项目成员。"""
    async with async_session() as session:
        try:
            data = await project_service.get_project_members(session, params.project_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_add_project_member", annotations=WRITE)
@audited_tool("admin_add_project_member")
async def admin_add_project_member(params: ProjectMemberInput) -> str:
    """添加项目成员。返回 {added:true}。"""
    async with async_session() as session:
        try:
            await project_service.add_project_member(
                session, params.project_id, params.user_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {"added": True, "project_id": params.project_id, "user_id": params.user_id}
    )


@mcp.tool(name="admin_remove_project_member", annotations=DELETE)
@audited_tool("admin_remove_project_member")
async def admin_remove_project_member(params: ProjectMemberInput) -> str:
    """移除项目成员。返回 {removed:true}。"""
    async with async_session() as session:
        try:
            await project_service.remove_project_member(
                session, params.project_id, params.user_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {"removed": True, "project_id": params.project_id, "user_id": params.user_id}
    )
