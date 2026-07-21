import logging
import os
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import Skill, SkillCategory, SkillUsageLog, SkillVersion
from repositories import skill_repo, skill_version_repo
from services import versioning_service
from services.skill_serializers import _latest_audit_map, _serialize, _serialize_version

logger = logging.getLogger(__name__)


async def record_skill_usage(
    session: AsyncSession,
    user_id: int,
    skill_id: int,
    action: str,
    ai_key_id: int | None = None,
) -> None:
    """记录 Skill 使用日志（download / install / agent_download）。失败不影响主流程。"""
    try:
        log = SkillUsageLog(
            user_id=user_id,
            skill_id=skill_id,
            action=action,
            ai_key_id=ai_key_id,
        )
        session.add(log)
        await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("record skill usage failed", exc_info=True)


def _ensure_skills_dir() -> str:
    base = settings.skills_storage_dir
    os.makedirs(base, exist_ok=True)
    return base


async def _download_from_url(url: str) -> tuple[bytes, str]:
    """下载远程 zip 文件，返回 (content, filename)。"""
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content = resp.content
    filename = url.rsplit("/", 1)[-1] or "skill.zip"
    if not filename.endswith(".zip"):
        filename += ".zip"
    return content, filename


# ─── Skill CRUD ──────────────────────────────────────────────────────────────


async def list_skills(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    category: str | None = None,
    is_published: bool | None = None,
    viewer_id: int | None = None,
    is_admin: bool = False,
) -> dict:
    total = await skill_repo.count_all(
        session,
        category=category,
        is_published=is_published,
        viewer_id=viewer_id,
        is_admin=is_admin,
    )
    items = await skill_repo.find_all(
        session,
        page=page,
        page_size=page_size,
        category=category,
        is_published=is_published,
        viewer_id=viewer_id,
        is_admin=is_admin,
    )
    latest_audit_map = await _latest_audit_map(session, items)
    serialized = [_serialize(s, latest_audit_map) for s in items]
    from services import rating_service

    await rating_service.enrich_items_with_ratings(session, "skill", serialized)
    return {
        "items": serialized,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_skill(session: AsyncSession, skill_id: int) -> dict:
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    latest_audit_map = await _latest_audit_map(session, [skill])
    return _serialize(skill, latest_audit_map)


async def create_skill(
    session: AsyncSession,
    name: str,
    icon: str = "📦",
    description: str = "",
    category: str = "general",
    version: str = "1.0.0",
    tags: list | None = None,
    author: str = "",
    agent_install_prompt: str = "",
    usage_instructions: str = "",
    is_published: bool = False,
    requires_approval: bool = False,
    visibility_type: str = "all",
    zip_content: bytes | None = None,
    zip_filename: str = "",
    source_url: str | None = None,
    created_by: int | None = None,
) -> dict:
    if not zip_content and not source_url:
        raise ValidationError("请上传 zip 包或提供仓库 URL")

    existing = await skill_repo.find_by_name(session, name)
    if existing:
        raise ConflictError(f"Skill 名称 '{name}' 已存在")

    if source_url:
        from core.url_safety import validate_url
        from core.url_translator import translate_repo_url

        translated = translate_repo_url(source_url)
        validate_url(translated.download_url, profile="default")
        zip_content, zip_filename = await _download_from_url(translated.download_url)

    sid = str(uuid.uuid4())
    zip_path = ""
    zip_size = 0
    if zip_content:
        base_dir = _ensure_skills_dir()
        safe_filename = f"{sid}.zip"
        full_path = os.path.join(base_dir, safe_filename)
        with open(full_path, "wb") as f:
            f.write(zip_content)
        zip_path = full_path
        zip_size = len(zip_content)

    # 发布门控：开启时发布动作转提交申请，资源先以未发布态落库
    from services import publish_review_service as _prs

    effective_published, submit_review_flag = await _prs.resolve_publish(
        session, is_published
    )

    skill = Skill(
        skill_id=sid,
        name=name,
        icon=icon,
        description=description,
        category=category,
        version=version,
        tags=tags or [],
        author=author,
        agent_install_prompt=agent_install_prompt,
        usage_instructions=usage_instructions,
        zip_path=zip_path,
        zip_size=zip_size,
        zip_filename=zip_filename,
        is_published=effective_published,
        requires_approval=requires_approval,
        visibility_type=visibility_type,
        created_by=created_by,
    )
    skill = await skill_repo.create(session, skill)

    # 门控开启时把发布动作转为评审申请（资源保持未发布）
    if submit_review_flag and created_by:
        await _prs.submit_review(session, _prs.ENTITY_SKILL, skill.id, created_by)

    # 发布且不需要审批时，自动同步到所有主 Key
    if skill.is_published and not skill.requires_approval:
        from services import ai_key_service

        await ai_key_service.sync_public_resource_to_all_keys(
            session, "skills", skill.id
        )

    await session.commit()
    await session.refresh(skill)

    # 为新 Skill 种入 v1 active 版本（与存量回填一致）
    v1 = SkillVersion(
        skill_id=skill.id,
        version=version,
        is_active=True,
        lifecycle_status="active",
        source="manual",
        zip_path=zip_path,
        zip_size=zip_size,
        zip_filename=zip_filename,
        agent_install_prompt=agent_install_prompt,
        usage_instructions=usage_instructions,
        change_log="initial version",
        security_status="not_scanned",
        created_by=created_by,
    )
    v1 = await skill_version_repo.create(session, v1)

    # 解析 SKILL.md 内容（write-time，零查询期开销）
    if zip_content:
        from services import skill_content_service

        parsed = skill_content_service.parse_skill_zip(zip_content)
        skill_content_service.apply_parsed_to_version(v1, parsed)
        skill.frontmatter = parsed.frontmatter
        skill.summary_text = parsed.summary_text

    skill.current_version_id = v1.id
    await session.commit()
    await session.refresh(skill)
    return _serialize(skill)


async def update_skill(
    session: AsyncSession,
    skill_id: int,
    actor_id: int | None = None,
    zip_content: bytes | None = None,
    zip_filename: str | None = None,
    **kwargs,
) -> dict:
    """更新 Skill 元数据。

    内容（zip）变更走 create_version + activate_version + 版本绑定安全审查，
    不在此处直接覆盖 active 内容，避免与版本模型冲突。zip_* 参数仅为兼容旧调用签名。
    """
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)

    was_published = skill.is_published
    for key, value in kwargs.items():
        if hasattr(skill, key) and value is not None:
            setattr(skill, key, value)

    # 发布门控：False→True 变更且门控开启时，转提交申请，保持未发布
    if not was_published and skill.is_published and actor_id is not None:
        from services import publish_review_service, publish_settings_service

        if await publish_settings_service.is_gate_enabled(session):
            skill.is_published = False
            await publish_review_service.submit_review(
                session, publish_review_service.ENTITY_SKILL, skill_id, actor_id
            )

    # 发布且不需要审批时同步到所有主 Key，否则从主 Key 中移除
    if skill.is_published and not skill.requires_approval:
        from services import ai_key_service

        await ai_key_service.sync_public_resource_to_all_keys(
            session, "skills", skill.id
        )
    else:
        from services import ai_key_service

        await ai_key_service.remove_public_resource_from_all_keys(
            session, "skills", skill.id
        )

    await session.commit()
    await session.refresh(skill)
    return _serialize(skill)


async def set_published(
    session: AsyncSession, skill_id: int, value: bool
) -> None:
    """审核通过后置 is_published（绕过门控，直接生效 + ai_key 同步）。"""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    skill.is_published = value
    from services import ai_key_service

    if value and not skill.requires_approval:
        await ai_key_service.sync_public_resource_to_all_keys(
            session, "skills", skill.id
        )
    else:
        await ai_key_service.remove_public_resource_from_all_keys(
            session, "skills", skill.id
        )
    await session.flush()


def _version_zip_dir(skill_uuid: str) -> str:
    """单个 Skill 的版本 zip 存储目录：{skills_storage_dir}/{skill_uuid}/"""
    skill_dir = os.path.join(settings.skills_storage_dir, skill_uuid)
    os.makedirs(skill_dir, exist_ok=True)
    return skill_dir


async def delete_skill(session: AsyncSession, skill_id: int) -> None:
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    # 收集所有版本各自的 zip 文件去重后清理（v1 可能与主表同路径）
    version_paths = {v.zip_path for v in (skill.versions or []) if v.zip_path}
    if skill.zip_path:
        version_paths.add(skill.zip_path)
    for path in version_paths:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                logger.warning("failed to remove zip file: %s", path)
    from services import ai_key_service

    await ai_key_service.remove_public_resource_from_all_keys(
        session, "skills", skill_id
    )
    await skill_repo.delete(session, skill_id)
    await session.commit()


async def get_skill_zip(
    session: AsyncSession, skill_id: int, require_published: bool = False
) -> tuple[str, str, int]:
    """返回 (zip_path, zip_filename, zip_size)。同时增加下载计数。"""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    if require_published and not skill.is_published:
        raise NotFoundError("skill", skill_id)
    if not skill.zip_path or not os.path.exists(skill.zip_path):
        raise NotFoundError("skill_zip", skill_id)

    skill.install_count = (skill.install_count or 0) + 1
    await session.commit()

    download_name = skill.zip_filename or f"{skill.name}.zip"
    return skill.zip_path, download_name, skill.zip_size


async def get_install_info(
    session: AsyncSession, skill_id: int, user_id: int | None = None
) -> dict:
    """返回 Skill 安装信息：介绍 / agent prompt / 使用说明。
    agent_prompt 由后端按 platform_public_url 拼接的下载 URL 自动生成。
    若提供 user_id，会查找用户主 Key 并在 URL 中嵌入 token。
    """
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)

    base_url = settings.platform_public_url.rstrip("/")
    download_url = f"{base_url}/api/v1/skills/{skill.id}/zip"

    if user_id:
        from repositories import ai_key_repo

        main_key = await ai_key_repo.find_personal_main(session, user_id)
        if main_key and main_key.litellm_key_id:
            download_url = f"{download_url}?token={main_key.litellm_key_id}"

    agent_prompt = f"请帮我下载{download_url} 并安装 {skill.name} 这个skill"

    return {
        "name": skill.name,
        "description": skill.description or "",
        "author": skill.author or "",
        "agent_prompt": agent_prompt,
        "download_url": download_url,
        "usage_instructions": skill.usage_instructions or "",
    }


# ─── Skill Versions ──────────────────────────────────────────────────────────

# 激活硬门控：必须通过安全审查（passed / attention_required）才允许激活新版本
_ACTIVATE_ALLOWED_DECISIONS = ("passed", "attention_required")


async def list_versions(
    session: AsyncSession,
    skill_id: int,
    include_deprecated: bool = True,
) -> list[dict]:
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    versions = await skill_version_repo.list_versions(
        session, skill_id, include_deprecated
    )
    return [_serialize_version(v) for v in versions]


async def create_version(
    session: AsyncSession,
    skill_id: int,
    *,
    version: str,
    zip_content: bytes | None = None,
    zip_filename: str = "",
    version_label: str = "",
    agent_install_prompt: str = "",
    usage_instructions: str = "",
    change_log: str = "",
    source: str = "manual",
    created_by: int | None = None,
) -> dict:
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    if await skill_version_repo.find_by_skill_and_version(session, skill_id, version):
        raise ConflictError(f"版本号 '{version}' 已存在")

    v = SkillVersion(
        skill_id=skill_id,
        version=version,
        version_label=version_label,
        is_active=False,
        lifecycle_status="inactive",
        source=source,
        agent_install_prompt=agent_install_prompt or skill.agent_install_prompt,
        usage_instructions=usage_instructions or skill.usage_instructions,
        change_log=change_log,
        security_status="not_scanned",
        created_by=created_by,
    )
    v = await skill_version_repo.create(session, v)

    if zip_content:
        skill_dir = _version_zip_dir(skill.skill_id)
        zip_path = os.path.join(skill_dir, f"{v.id}.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_content)
        v.zip_path = zip_path
        v.zip_size = len(zip_content)
        v.zip_filename = zip_filename

        # 解析新 ZIP 的 SKILL.md 内容
        from services import skill_content_service

        parsed = skill_content_service.parse_skill_zip(zip_content)
        skill_content_service.apply_parsed_to_version(v, parsed)
    elif skill.zip_path:
        # 未上传新 zip：fork 当前 active 内容作为新版本起点
        v.zip_path = skill.zip_path
        v.zip_size = skill.zip_size
        v.zip_filename = skill.zip_filename

    await session.commit()
    await session.refresh(v)
    return _serialize_version(v)


async def activate_version(
    session: AsyncSession, skill_id: int, version_id: int
) -> dict:
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    version = await skill_version_repo.find_by_id(session, version_id)
    if not version or version.skill_id != skill_id:
        raise NotFoundError("skill_version", version_id)

    # 幂等：已是 active 直接返回，不触发门控
    if version.is_active:
        latest_audit_map = await _latest_audit_map(session, [skill])
        return _serialize(skill, latest_audit_map)

    # 硬门控：未通过安全审查的新版本不可激活
    if not (
        version.security_status == "completed"
        and version.security_decision in _ACTIVATE_ALLOWED_DECISIONS
    ):
        raise ValidationError("新版本未通过安全审查，不可激活")

    await versioning_service.activate_version(
        session,
        version,
        skill,
        skill_id,
        skill_version_repo,
        on_sync=_noop_sync,
        apply_snapshot=_apply_version_snapshot_to_skill,
    )
    await session.refresh(skill)
    latest_audit_map = await _latest_audit_map(session, [skill])
    return _serialize(skill, latest_audit_map)


async def deprecate_version(
    session: AsyncSession,
    skill_id: int,
    version_id: int,
    sunset_date: datetime | None = None,
) -> dict:
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    version = await skill_version_repo.find_by_id(session, version_id)
    if not version or version.skill_id != skill_id:
        raise NotFoundError("skill_version", version_id)

    await versioning_service.deprecate(
        session, version, skill_version_repo, sunset_date
    )
    version = await skill_version_repo.find_by_id(session, version_id)
    return _serialize_version(version)


async def _noop_sync(skill: Skill, version: SkillVersion) -> None:
    """Skill 不进 LiteLLM，激活无外部系统同步。"""


async def _apply_version_snapshot_to_skill(skill: Skill, version: SkillVersion) -> None:
    """把 active 版本的内容/安全快照拷贝到主表（主表 = active 版本冗余快照）。"""
    skill.zip_path = version.zip_path
    skill.zip_size = version.zip_size
    skill.zip_filename = version.zip_filename
    skill.version = version.version
    skill.agent_install_prompt = version.agent_install_prompt
    skill.usage_instructions = version.usage_instructions
    skill.security_status = version.security_status
    skill.security_decision = version.security_decision
    skill.security_severity = version.security_severity
    skill.security_risk_score = version.security_risk_score
    skill.latest_ai_policies_audit_id = version.latest_ai_policies_audit_id
    skill.frontmatter = version.frontmatter
    skill.summary_text = version.summary_text


# ─── Categories ──────────────────────────────────────────────────────────────


async def list_categories(session: AsyncSession) -> list[dict]:
    cats = await skill_repo.list_categories(session)
    return [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "sort_order": c.sort_order,
        }
        for c in cats
    ]


async def create_category(
    session: AsyncSession, name: str, description: str = "", sort_order: int = 0
) -> dict:
    existing = await skill_repo.find_category_by_name(session, name)
    if existing:
        raise ConflictError(f"分类 '{name}' 已存在")
    cat = SkillCategory(name=name, description=description, sort_order=sort_order)
    cat = await skill_repo.create_category(session, cat)
    await session.commit()
    return {
        "id": cat.id,
        "name": cat.name,
        "description": cat.description,
        "sort_order": cat.sort_order,
    }


async def delete_category(session: AsyncSession, category_id: int) -> None:
    cat = await skill_repo.find_category_by_id(session, category_id)
    if not cat:
        raise NotFoundError("skill_category", category_id)
    await skill_repo.delete_category(session, category_id)
    await session.commit()
