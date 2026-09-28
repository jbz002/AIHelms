"""贡献者 Skill 上传编排：预检 → 落库 → 自动激活 → 发布（门控自决）。

设计约定（2026-09 需求 3/4）：
- 上传即最新版，激活版本默认跟随最新版；首传版本自动激活，无「设为激活」UI。
- 多版本共存后，owner 可在 web 端手动切换激活版本（contributor activate 端点）。
- 领用默认免审批（requires_approval=False）；发布是否需审核由发布门控决定
  （create_skill 内 resolve_publish）：门控关 = 上传即发布，门控开 = 自动提审。
  推版本不提审（首审挡入口，后续版本信任 owner）。
- 可见性：调用方不传 → 默认按创建者部门（无部门回退 all）；显式传 all/department
  等值则尊重调用方（web 表单可见范围选择器 / 外部系统程序化上传均走此参数）。

三步是各自独立可复用的 service 调用（skill_service），本模块只做顺序编排；
admin 链路不经过这里。contributor（JWT）与 CLI 通道（API Key + skill:publish
scope）共用本编排。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from repositories import department_repo, skill_version_repo
from services import skill_service, visibility_service
from services.skill_protocol_service import validate_skill_package_or_raise
from services.skill_serializers import _serialize_version


async def resolve_creator_default_visibility(
    session: AsyncSession, created_by: int
) -> tuple[str, int | None]:
    """贡献者默认可见性：有部门 → department + 最早加入部门；无部门 → all。"""
    department_ids = await department_repo.find_user_department_ids(session, created_by)
    if department_ids:
        return visibility_service.DEPARTMENT, department_ids[0]
    return visibility_service.ALL, None


async def _resolve_visibility(
    session: AsyncSession, requested: str | None, created_by: int
) -> tuple[str, int | None]:
    """可见性裁决：显式指定优先，department 需解析部门（无部门回退 all）。"""
    if not requested:
        return await resolve_creator_default_visibility(session, created_by)
    if requested == visibility_service.DEPARTMENT:
        default_type, department_id = await resolve_creator_default_visibility(
            session, created_by
        )
        if default_type == visibility_service.ALL:
            return visibility_service.ALL, None
        return visibility_service.DEPARTMENT, department_id
    return requested, None


async def create_contribution_and_submit(
    session: AsyncSession,
    *,
    name: str,
    icon: str = "📦",
    icon_url: str | None = None,
    description: str = "",
    category: str = "general",
    version: str = "1.0.0",
    tags: list | None = None,
    author: str = "",
    agent_install_prompt: str = "",
    usage_instructions: str = "",
    visibility_type: str | None = None,
    source_url: str | None = None,
    zip_content: bytes | None = None,
    zip_filename: str = "",
    created_by: int,
) -> dict:
    """上传编排：物化 zip → 双重预检 → 创建（免审批 + 可见性裁决）→ 激活 v1 → 发布。

    is_published=True 交给 create_skill 门控自决：门控关直接发布；门控开由其内部
    转提审（此处不再显式 submit_review，避免双重提审撞 409）。
    """
    if source_url and not zip_content:
        zip_content, zip_filename = await skill_service.fetch_skill_zip_from_url(
            source_url
        )
    if zip_content:
        validate_skill_package_or_raise(zip_content, f"contribution create {name}")

    effective_visibility, department_id = await _resolve_visibility(
        session, visibility_type, created_by
    )
    if not author:
        # 上传者联动：调用方（ai-assistant 等）不传 author 时回填创建者姓名
        from repositories import user_repo

        creator = await user_repo.find_user_by_id(session, created_by)
        author = (creator.display_name or creator.username) if creator else ""
    created = await skill_service.create_skill(
        session,
        name=name,
        icon=icon,
        icon_url=icon_url,
        description=description,
        category=category,
        version=version,
        tags=tags,
        author=author,
        agent_install_prompt=agent_install_prompt,
        usage_instructions=usage_instructions,
        is_published=True,
        requires_approval=False,
        visibility_type=effective_visibility,
        visible_department_id=department_id,
        zip_content=zip_content,
        zip_filename=zip_filename,
        source_url=source_url,
        created_by=created_by,
    )
    await skill_service.activate_version(
        session, int(created["id"]), int(created["current_version_id"])
    )
    return created


async def create_contribution_version_and_activate(
    session: AsyncSession,
    skill_id: int,
    *,
    version: str,
    version_label: str = "",
    change_log: str = "",
    zip_content: bytes | None = None,
    zip_filename: str = "",
    created_by: int,
) -> dict:
    """版本上传编排：预检 → 创建新版本 → 自动激活（激活版本始终跟随最新版）。

    返回激活后的版本序列化（lifecycle=published / is_active=True）。
    """
    if zip_content:
        validate_skill_package_or_raise(
            zip_content, f"contribution version skill_id={skill_id} v={version}"
        )
    created_version = await skill_service.create_version(
        session,
        skill_id,
        version=version,
        version_label=version_label,
        change_log=change_log,
        zip_content=zip_content,
        zip_filename=zip_filename,
        created_by=created_by,
    )
    # 预检已挡 zip 源协议问题；此处失败仅剩 fork 源存量包异常，直接抛给用户
    await skill_service.activate_version(session, skill_id, int(created_version["id"]))
    activated = await skill_version_repo.find_by_id(session, int(created_version["id"]))
    return _serialize_version(activated)
