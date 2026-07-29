import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import async_session
from core.distributed_lock import redis_lock
from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import Skill, SkillCategory, SkillUsageLog, SkillVersion
from repositories import (
    ai_policies_repo,
    skill_repo,
    skill_tag_repo,
    skill_version_repo,
    storage_deletion_compensation_repo,
)
from services import skill_tag_service, versioning_service
from services.icon_url import normalize_hosted_icon_path
from services.skill_content_service import ParsedSkillContent
from services.skill_lifecycle_service import (
    DRAFT,
    PENDING_REVIEW,
    PUBLISHED,
    YANKED,
)
from services.skill_serializers import (
    _latest_audit_map,
    _serialize,
    _serialize_version,
)

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
    version_tags_map = await _build_version_tags_map(session, skill.id)
    return _serialize(
        skill,
        latest_audit_map,
        version_tags_map=version_tags_map,
    )


async def _build_version_tags_map(
    session: AsyncSession, skill_id: int
) -> dict[int, list[str]]:
    """单 skill 详情：按 version_id 分组的 tag_name 映射。"""
    tags = await skill_tag_repo.find_by_skill(session, skill_id)
    mapping: dict[int, list[str]] = {}
    for tag in tags:
        mapping.setdefault(tag.version_id, []).append(tag.tag_name)
    return mapping


async def create_skill(
    session: AsyncSession,
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
        _validate_package_or_raise(zip_content, "create_skill")
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
        icon_url=normalize_hosted_icon_path(icon_url),
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

    # 满足公开列表可见条件时，自动广播同步到所有主 Key
    if _is_list_visible_to_public(skill):
        from services import ai_key_service

        await ai_key_service.sync_public_resource_to_all_keys(
            session, "skills", skill.id
        )

    await session.commit()
    await session.refresh(skill)

    # 为新 Skill 种入 v1 草稿版本
    v1 = SkillVersion(
        skill_id=skill.id,
        version=version,
        is_active=False,
        lifecycle_status="draft",
        source="manual",
        source_type="url" if source_url else "zip",
        source_url=source_url or "",
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

    # 解析 SKILL.md 内容 + 协议合规校验（write-time，零查询期开销）
    if zip_content:
        parsed = _parse_validate_and_apply(v1, zip_content)
        skill.frontmatter = parsed.frontmatter
        skill.summary_text = parsed.summary_text

    skill.current_version_id = v1.id
    await session.commit()
    await session.refresh(skill)
    await skill_tag_service.refresh_latest_tag(session, skill.id)
    return _serialize(skill)


def _is_list_visible_to_public(skill: Skill) -> bool:
    """Skill 是否进入全体用户的 published 列表，从而广播同步到所有主 Key。

    与 skill_repo.find_all 对非 admin 的过滤保持一致：
    is_published 且无需审批 且未治理下架 且可见性为 all/selected。
    private/unlisted 不进列表，不广播到主 Key（避免用户端展示成 #id 孤儿）。
    """
    from services import visibility_service

    return (
        skill.is_published
        and not skill.requires_approval
        and not skill.hidden
        and skill.visibility_type in visibility_service.LIST_VISIBLE_TYPES
    )


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
    if "icon_url" in kwargs:
        kwargs["icon_url"] = normalize_hosted_icon_path(kwargs["icon_url"])
    elif "icon" in kwargs:
        skill.icon_url = None
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

    # 满足公开列表可见条件才广播同步到所有主 Key，否则移除（覆盖下架/隐藏/可见性变更）
    from services import ai_key_service

    if _is_list_visible_to_public(skill):
        await ai_key_service.sync_public_resource_to_all_keys(
            session, "skills", skill.id
        )
    else:
        await ai_key_service.remove_public_resource_from_all_keys(
            session, "skills", skill.id
        )

    await session.commit()
    await session.refresh(skill)
    return _serialize(skill)


async def set_published(session: AsyncSession, skill_id: int, value: bool) -> None:
    """审核通过后置 is_published（绕过门控，直接生效 + ai_key 同步）。"""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    skill.is_published = value
    from services import ai_key_service

    if _is_list_visible_to_public(skill):
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


def _parse_validate_and_apply(
    version: SkillVersion, zip_bytes: bytes
) -> ParsedSkillContent:
    """解析 SKILL.md + 协议校验 + 写内容与协议字段到版本 ORM。

    草稿容错：errors 入库不阻断注册，由 activate_version 门控。
    file_hashes 用 manifest 结果覆盖（含 content_type/category）。
    """
    from services import skill_content_service, skill_protocol_service

    parsed = skill_content_service.parse_skill_zip(zip_bytes)
    skill_content_service.apply_parsed_to_version(version, parsed)
    result = skill_protocol_service.validate_skill_protocol(parsed)
    version.file_hashes = result.manifest
    version.protocol_valid = result.valid
    version.protocol_errors = result.to_storage_list()
    version.last_validated_at = datetime.now(timezone.utc)
    return parsed


_PACKAGE_ERROR_CAP = 20


def _validate_package_or_raise(zip_bytes: bytes, context_label: str) -> None:
    """S5 物理安全门控：包校验失败抛 ValidationError（→ 400），整包不落盘。

    在 create_skill / create_version 写盘前调用，先于 S1 协议校验与内容解析。
    """
    from services import skill_package_validator

    result = skill_package_validator.validate_skill_package(zip_bytes)
    if result.valid:
        return
    lines = [f"Skill 包物理校验未通过（{context_label}）："]
    for issue in result.errors[:_PACKAGE_ERROR_CAP]:
        suffix = f"（文件：{issue.file_path}）" if issue.file_path else ""
        lines.append(f"- {issue.message}{suffix}")
    dropped = len(result.errors) - _PACKAGE_ERROR_CAP
    if dropped > 0:
        lines.append(f"- ……另有 {dropped} 条问题，详见服务端日志")
    logger.warning(
        "skill package rejected: %d errors, %d files, %d bytes, context=%s",
        len(result.errors),
        result.checked_files,
        result.uncompressed_bytes,
        context_label,
    )
    raise ValidationError("\n".join(lines))


def _validate_fork_version(version: SkillVersion, zip_path: str) -> None:
    """fork 分支：从磁盘读存量 zip 复跑协议校验；读不到则标记未校验。"""
    try:
        with open(zip_path, "rb") as f:
            zip_bytes = f.read()
    except OSError:
        logger.warning("failed to read fork zip: %s", zip_path)
        version.protocol_valid = False
        version.protocol_errors = [
            {
                "severity": "error",
                "code": "fork.zip_unreadable",
                "message": "未上传新 zip 且无法读取存量包，跳过协议校验",
            }
        ]
        version.last_validated_at = datetime.now(timezone.utc)
        return
    _parse_validate_and_apply(version, zip_bytes)


async def delete_skill(session: AsyncSession, skill_id: int) -> None:
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    # 收集所有版本各自的 zip 文件去重（v1 可能与主表同路径）
    version_paths = {v.zip_path for v in (skill.versions or []) if v.zip_path}
    if skill.zip_path:
        version_paths.add(skill.zip_path)

    from services import ai_key_service

    # 先提交 DB（主 Key 同步、审计标记、删除主表），成功后再清文件。
    # 文件清理失败不回滚 DB，记补偿记录由定时任务重试，避免孤儿文件。
    await ai_key_service.remove_public_resource_from_all_keys(
        session, "skills", skill_id
    )
    await ai_policies_repo.mark_audits_deleted_for_skill(session, skill_id)
    await skill_repo.delete(session, skill_id)
    await session.commit()

    await _purge_files_after_commit("skill", skill_id, version_paths)


async def _purge_files_after_commit(
    entity_type: str, entity_id: int, paths: set[str]
) -> None:
    """DB 提交后清理文件；失败写补偿记录（独立 session）。"""
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        try:
            os.remove(path)
        except OSError as exc:
            logger.warning("failed to remove file, record compensation: %s", path)
            try:
                async with async_session() as comp_session:
                    await storage_deletion_compensation_repo.create(
                        comp_session,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        storage_path=path,
                        last_error=str(exc),
                    )
                    await comp_session.commit()
            except Exception:  # noqa: BLE001
                logger.exception("record storage compensation failed: %s", path)


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
    session: AsyncSession,
    skill_id: int,
    user_id: int | None = None,
    base_url_override: str | None = None,
) -> dict:
    """返回 Skill 安装信息：介绍 / agent prompt / 使用说明。
    agent_prompt 由后端按 platform_public_url 拼接的下载 URL 自动生成。
    若提供 user_id，会查找用户主 Key 并在 URL 中嵌入 token。
    base_url_override 优先于 settings.platform_public_url，用于按当前请求主机名生成下载地址。
    """
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)

    base_url = (base_url_override or settings.platform_public_url).rstrip("/")
    download_url = f"{base_url}/api/v1/skills/{skill.id}/zip"

    if user_id:
        from repositories import ai_key_repo

        main_key = await ai_key_repo.find_personal_main(session, user_id)
        if main_key and main_key.litellm_key_id:
            download_url = f"{download_url}?token={main_key.litellm_key_id}"

    agent_prompt = f"请帮我下载{download_url} 并安装 {skill.name} 这个skill"

    active = await skill_version_repo.find_active_for_skill(session, skill.id)
    return {
        "name": skill.name,
        "description": skill.description or "",
        "author": skill.author or "",
        "agent_prompt": agent_prompt,
        "download_url": download_url,
        "usage_instructions": skill.usage_instructions or "",
        "protocol_valid": active.protocol_valid if active else False,
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
    audit_ids = [
        v.latest_ai_policies_audit_id for v in versions if v.latest_ai_policies_audit_id
    ]
    audits = await ai_policies_repo.find_by_ids(session, audit_ids)
    audit_code_map = {a.id: a.audit_id for a in audits}
    return [
        _serialize_version(
            v, audit_code=audit_code_map.get(v.latest_ai_policies_audit_id)
        )
        for v in versions
    ]


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
    source_url: str = "",
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
        lifecycle_status="draft",
        source=source,
        source_type="url" if source_url else "zip",
        source_url=source_url or "",
        agent_install_prompt=agent_install_prompt or skill.agent_install_prompt,
        usage_instructions=usage_instructions or skill.usage_instructions,
        change_log=change_log,
        security_status="not_scanned",
        created_by=created_by,
    )
    v = await skill_version_repo.create(session, v)

    if zip_content:
        _validate_package_or_raise(
            zip_content, f"create_version skill_id={skill_id} v={version}"
        )
        skill_dir = _version_zip_dir(skill.skill_id)
        zip_path = os.path.join(skill_dir, f"{v.id}.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_content)
        v.zip_path = zip_path
        v.zip_size = len(zip_content)
        v.zip_filename = zip_filename

        # 解析 SKILL.md + 协议合规校验
        _parse_validate_and_apply(v, zip_content)
    elif skill.zip_path:
        # 未上传新 zip：fork 当前 active 内容作为新版本起点
        v.zip_path = skill.zip_path
        v.zip_size = skill.zip_size
        v.zip_filename = skill.zip_filename
        # fork 版本也复跑协议校验，保证激活门控有据可查
        _validate_fork_version(v, skill.zip_path)

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

    # 状态守卫：draft / pending_review / published 可激活。
    # published 含历史已发布版本（is_active=False），允许回切为当前激活；
    # scanning / yanked / rejected / deprecated 不可激活。
    if version.lifecycle_status not in (DRAFT, PENDING_REVIEW, PUBLISHED):
        raise ValidationError(f"版本当前状态为 {version.lifecycle_status}，不可激活")

    # 硬门控：必须通过安全审查（passed / attention_required）才可激活
    security_ok = (
        version.security_status == "completed"
        and version.security_decision in _ACTIVATE_ALLOWED_DECISIONS
    )
    if not security_ok:
        raise ValidationError("新版本未通过安全审查，不可激活")

    # 协议门控：SKILL.md 协议校验未通过不可激活（草稿容错，仅在激活时阻断）
    if not version.protocol_valid:
        detail = "；".join(
            issue["message"]
            for issue in (version.protocol_errors or [])
            if issue.get("severity") == "error"
        )
        raise ValidationError(
            f"版本协议校验未通过，不可激活：{detail or '存在协议合规错误'}"
        )

    await versioning_service.activate_version(
        session,
        version,
        skill,
        skill_id,
        skill_version_repo,
        on_sync=_noop_sync,
        apply_snapshot=_apply_version_snapshot_to_skill,
    )
    await skill_tag_service.refresh_latest_tag(session, skill_id)
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


async def activate_version_builtin(
    session: AsyncSession, skill_id: int, version_id: int
) -> dict:
    """S8 · 内置 skill 版本直接激活。

    绕过 activate_version 的安全/协议门控（内置内容由平台预审，等同 create_skill
    v1 直接 published 的语义），但复用 versioning_service 的单 active 激活机制，
    维持「先 noop 同步 → 降级其它 active → 置目标 active/published → 快照回主表」
    不变式与正常激活完全一致。
    """
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    version = await skill_version_repo.find_by_id(session, version_id)
    if not version or version.skill_id != skill_id:
        raise NotFoundError("skill_version", version_id)
    if version.is_active:
        return _serialize(skill, await _latest_audit_map(session, [skill]))
    await versioning_service.activate_version(
        session,
        version,
        skill,
        skill_id,
        skill_version_repo,
        on_sync=_noop_sync,
        apply_snapshot=_apply_version_snapshot_to_skill,
    )
    await skill_tag_service.refresh_latest_tag(session, skill_id)
    await session.refresh(skill)
    return _serialize(skill, await _latest_audit_map(session, [skill]))


# ─── S3 · 生命周期状态机精细化 ────────────────────────────────────────────────


async def yank_version(session: AsyncSession, skill_id: int, version_id: int) -> dict:
    """撤回已发布版本：published → yanked，命中 current_version_id 则重算次新 published。"""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    version = await skill_version_repo.find_by_id(session, version_id)
    if not version or version.skill_id != skill_id:
        raise NotFoundError("skill_version", version_id)

    async with redis_lock(f"aihelms:lock:skill_yank:{skill_id}"):
        version = await skill_version_repo.find_by_id(session, version_id)
        if version.lifecycle_status != PUBLISHED:
            raise ValidationError(
                f"版本当前状态为 {version.lifecycle_status}，仅 published 可撤回"
            )
        version.lifecycle_status = YANKED
        version.is_active = False
        # 先落 yanked 翻转，避免重算时与 single-active 部分唯一索引冲突
        await session.flush()

        # 命中当前 published 指针 → 重算次新 published，回滚主表快照
        if skill.current_version_id == version_id:
            new_latest = await skill_version_repo.find_latest_published(
                session, skill_id, exclude_version_id=version_id
            )
            if new_latest:
                new_latest.is_active = True
                skill.current_version_id = new_latest.id
                await _apply_version_snapshot_to_skill(skill, new_latest)
            else:
                skill.current_version_id = None
        await session.commit()
        await skill_tag_service.refresh_latest_tag(session, skill_id)
    await session.refresh(skill)
    latest_audit_map = await _latest_audit_map(session, [skill])
    return _serialize(skill, latest_audit_map)


async def restore_version(
    session: AsyncSession, skill_id: int, version_id: int
) -> dict:
    """恢复已撤回版本：yanked → published，撤销 yank 全部副作用。

    - 若 skill 当前无激活版本（current_version_id 为 None，单版本撤回场景）→
      重新激活本版本（is_active=True、current 回指、快照回主表、刷 tag），
      回到撤回前的激活态。
    - 若已有 active 版本（多版本场景）→ published+inactive 候选，不抢夺当前激活。

    复用 versioning_service.activate_version 做指针翻转 + 快照，与 activate 一致；
    版本撤回前已通过门控，撤回/恢复不改动 security/protocol 状态，故不重跑门控。
    """
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    version = await skill_version_repo.find_by_id(session, version_id)
    if not version or version.skill_id != skill_id:
        raise NotFoundError("skill_version", version_id)
    if version.lifecycle_status != YANKED:
        raise ValidationError(
            f"版本当前状态为 {version.lifecycle_status}，仅 yanked 可恢复"
        )
    version.lifecycle_status = PUBLISHED
    version.is_active = False
    await session.flush()
    # 撤回导致 skill 无激活版本 → 恢复即重新激活（撤销 yank 副作用）
    if skill.current_version_id is None:
        await versioning_service.activate_version(
            session,
            version,
            skill,
            skill_id,
            skill_version_repo,
            on_sync=_noop_sync,
            apply_snapshot=_apply_version_snapshot_to_skill,
        )
        await skill_tag_service.refresh_latest_tag(session, skill_id)
    else:
        await session.commit()
    await session.refresh(skill)
    latest_audit_map = await _latest_audit_map(session, [skill])
    return _serialize(skill, latest_audit_map)


async def set_hidden(
    session: AsyncSession,
    skill_id: int,
    hidden: bool,
    actor_id: int | None = None,
) -> dict:
    """治理下架 overlay 开关（独立于 lifecycle_status 与 visibility_type）。"""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    skill.hidden = hidden
    skill.hidden_at = datetime.now(timezone.utc) if hidden else None
    skill.hidden_by = actor_id if hidden else None
    # 治理下架/恢复需同步主 Key：下架后不进 published 列表，从所有主 Key 移除；
    # 恢复且满足公开可见条件时重新广播同步
    from services import ai_key_service

    if _is_list_visible_to_public(skill):
        await ai_key_service.sync_public_resource_to_all_keys(
            session, "skills", skill.id
        )
    else:
        await ai_key_service.remove_public_resource_from_all_keys(
            session, "skills", skill.id
        )
    await session.commit()
    await session.refresh(skill)
    latest_audit_map = await _latest_audit_map(session, [skill])
    return _serialize(skill, latest_audit_map)


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
