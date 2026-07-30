"""Skill 资源治理深化工具（M5）：更新/发布/隐藏/版本/分类。

drift/标签在 skill_drift_service/skill_tag_service（本批未覆盖，记偏差）。
"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import actor_id, error_text, json_dumps
from mcp_admin.server import mcp
from services import skill_service

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


class SkillIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    skill_id: int = Field(..., ge=1)


class UpdateSkillInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    skill_id: int = Field(..., ge=1)
    name: str | None = None
    description: str | None = None
    category: str | None = None
    icon_url: str | None = None
    agent_install_prompt: str | None = None
    usage_instructions: str | None = None
    is_published: bool | None = None
    requires_approval: bool | None = None
    visibility_type: str | None = None


class SkillBoolInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    skill_id: int = Field(..., ge=1)
    value: bool


class SkillVersionIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    skill_id: int = Field(..., ge=1)
    version_id: int = Field(..., ge=1)


class CreateSkillVersionInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    skill_id: int = Field(..., ge=1)
    version: str = Field(..., min_length=1)
    source_url: str = Field(default="", description="包来源 URL（不传二进制）")
    version_label: str = ""
    agent_install_prompt: str = ""
    usage_instructions: str = ""
    change_log: str = ""


class CategoryNameInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    sort_order: int = 0


class CategoryIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    category_id: int = Field(..., ge=1)


@mcp.tool(name="admin_update_skill", annotations=WRITE)
@audited_tool("admin_update_skill")
async def admin_update_skill(params: UpdateSkillInput) -> str:
    """更新 Skill 字段（None 字段不变）。返回更新后详情。"""
    actor = actor_id()
    kwargs = params.model_dump(exclude={"skill_id"}, exclude_none=True)
    async with async_session() as session:
        try:
            data = await skill_service.update_skill(
                session, params.skill_id, actor, **kwargs
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_set_skill_published", annotations=WRITE)
@audited_tool("admin_set_skill_published")
async def admin_set_skill_published(params: SkillBoolInput) -> str:
    """设置 Skill 发布状态。返回 {updated:true}。"""
    async with async_session() as session:
        try:
            await skill_service.set_published(session, params.skill_id, params.value)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(
        {"updated": True, "skill_id": params.skill_id, "is_published": params.value}
    )


@mcp.tool(name="admin_set_skill_hidden", annotations=WRITE)
@audited_tool("admin_set_skill_hidden")
async def admin_set_skill_hidden(params: SkillBoolInput) -> str:
    """设置 Skill 隐藏状态。返回更新后详情。"""
    actor = actor_id()
    async with async_session() as session:
        try:
            data = await skill_service.set_hidden(
                session, params.skill_id, params.value, actor
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_list_skill_versions", annotations=READ_ONLY)
async def admin_list_skill_versions(params: SkillIdInput) -> str:
    """列出 Skill 全部版本。"""
    async with async_session() as session:
        try:
            data = await skill_service.list_versions(session, params.skill_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_skill_version", annotations=WRITE)
@audited_tool("admin_create_skill_version")
async def admin_create_skill_version(params: CreateSkillVersionInput) -> str:
    """创建 Skill 新版本（包内容走 source_url，不传二进制）。返回新版本详情。"""
    created_by = actor_id()
    async with async_session() as session:
        try:
            data = await skill_service.create_version(
                session,
                params.skill_id,
                version=params.version,
                source_url=params.source_url,
                version_label=params.version_label,
                agent_install_prompt=params.agent_install_prompt,
                usage_instructions=params.usage_instructions,
                change_log=params.change_log,
                created_by=created_by,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_activate_skill_version", annotations=WRITE)
@audited_tool("admin_activate_skill_version")
async def admin_activate_skill_version(params: SkillVersionIdInput) -> str:
    """激活 Skill 指定版本。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await skill_service.activate_version(
                session, params.skill_id, params.version_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_deprecate_skill_version", annotations=WRITE)
@audited_tool("admin_deprecate_skill_version")
async def admin_deprecate_skill_version(params: SkillVersionIdInput) -> str:
    """弃用 Skill 指定版本。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await skill_service.deprecate_version(
                session, params.skill_id, params.version_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_yank_skill_version", annotations=WRITE)
@audited_tool("admin_yank_skill_version")
async def admin_yank_skill_version(params: SkillVersionIdInput) -> str:
    """下架 Skill 指定版本（不可安装，可恢复）。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await skill_service.yank_version(
                session, params.skill_id, params.version_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_restore_skill_version", annotations=WRITE)
@audited_tool("admin_restore_skill_version")
async def admin_restore_skill_version(params: SkillVersionIdInput) -> str:
    """恢复已下架的 Skill 版本。返回更新后详情。"""
    async with async_session() as session:
        try:
            data = await skill_service.restore_version(
                session, params.skill_id, params.version_id
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_list_skill_categories", annotations=READ_ONLY)
async def admin_list_skill_categories(params: SkillIdInput) -> str:
    """列出 Skill 分类。"""
    async with async_session() as session:
        try:
            data = await skill_service.list_categories(session)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_create_skill_category", annotations=WRITE)
@audited_tool("admin_create_skill_category")
async def admin_create_skill_category(params: CategoryNameInput) -> str:
    """创建 Skill 分类。返回新建详情。"""
    async with async_session() as session:
        try:
            data = await skill_service.create_category(
                session, params.name, params.description, params.sort_order
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(name="admin_delete_skill_category", annotations=DELETE)
@audited_tool("admin_delete_skill_category")
async def admin_delete_skill_category(params: CategoryIdInput) -> str:
    """删除 Skill 分类。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await skill_service.delete_category(session, params.category_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "category_id": params.category_id})
