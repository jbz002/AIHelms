"""Skill 管理工具（P0：读 + URL 创建 + 删）。"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_admin._audit import audited_tool
from mcp_admin._common import PageInput, actor_id, error_text, json_dumps
from mcp_admin.server import mcp
from services import skill_service


class ListSkillsInput(PageInput):
    category: str | None = Field(default=None, description="按分类过滤")
    is_published: bool | None = Field(default=None, description="按发布状态过滤")


class SkillIdInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    skill_id: int = Field(..., ge=1)


class CreateSkillFromUrlInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(..., description="Skill 名称")
    source_url: str = Field(
        ..., description="git/zip 仓库 URL，服务端会转换并校验后下载"
    )
    description: str = ""
    category: str = "general"
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list, description="标签名列表")
    author: str = ""
    is_published: bool = Field(
        default=False, description="默认未发布；开启门控会转评审"
    )
    requires_approval: bool = False
    visibility_type: str = "all"


@mcp.tool(
    name="admin_list_skills",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_list_skills(params: ListSkillsInput) -> str:
    """分页查询 Skill 列表（管理员视角，含未发布）。返回 {items,total,page,page_size}。"""
    async with async_session() as session:
        try:
            data = await skill_service.list_skills(
                session,
                params.page,
                params.page_size,
                params.category,
                params.is_published,
                is_admin=True,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_get_skill",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def admin_get_skill(params: SkillIdInput) -> str:
    """按 ID 查询 Skill 详情。"""
    async with async_session() as session:
        try:
            data = await skill_service.get_skill(session, params.skill_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_create_skill_from_url",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@audited_tool("admin_create_skill_from_url")
async def admin_create_skill_from_url(params: CreateSkillFromUrlInput) -> str:
    """从 git/zip URL 创建 Skill（服务端下载并校验包结构，含 SSRF 防护）。不走 zip 二进制入参。返回新建 Skill 详情。"""
    created_by = actor_id()
    async with async_session() as session:
        try:
            data = await skill_service.create_skill(
                session,
                name=params.name,
                description=params.description,
                category=params.category,
                version=params.version,
                tags=params.tags,
                author=params.author,
                is_published=params.is_published,
                requires_approval=params.requires_approval,
                visibility_type=params.visibility_type,
                source_url=params.source_url,
                created_by=created_by,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="admin_delete_skill",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@audited_tool("admin_delete_skill")
async def admin_delete_skill(params: SkillIdInput) -> str:
    """删除 Skill（含磁盘文件清理）。返回 {deleted:true}。"""
    async with async_session() as session:
        try:
            await skill_service.delete_skill(session, params.skill_id)
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps({"deleted": True, "skill_id": params.skill_id})
