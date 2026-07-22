from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError
from models.db import SkillVersion


async def create(session: AsyncSession, version: SkillVersion) -> SkillVersion:
    session.add(version)
    await session.flush()
    await session.refresh(version)
    return version


async def find_by_id(session: AsyncSession, version_id: int) -> SkillVersion | None:
    result = await session.execute(
        select(SkillVersion).where(SkillVersion.id == version_id)
    )
    return result.scalar_one_or_none()


async def find_active_for_skill(
    session: AsyncSession, skill_id: int
) -> SkillVersion | None:
    result = await session.execute(
        select(SkillVersion).where(
            SkillVersion.skill_id == skill_id,
            SkillVersion.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def find_latest_published(
    session: AsyncSession, skill_id: int, exclude_version_id: int | None = None
) -> SkillVersion | None:
    """S3 · Yank 指针重算：查次新 published 版本（排除指定版本，按 id 倒序）。"""
    stmt = select(SkillVersion).where(
        SkillVersion.skill_id == skill_id,
        SkillVersion.lifecycle_status == "published",
    )
    if exclude_version_id is not None:
        stmt = stmt.where(SkillVersion.id != exclude_version_id)
    stmt = stmt.order_by(SkillVersion.id.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def find_by_skill_and_version(
    session: AsyncSession, skill_id: int, version: str
) -> SkillVersion | None:
    result = await session.execute(
        select(SkillVersion).where(
            SkillVersion.skill_id == skill_id,
            SkillVersion.version == version,
        )
    )
    return result.scalar_one_or_none()


async def list_versions(
    session: AsyncSession,
    skill_id: int,
    include_deprecated: bool = True,
) -> list[SkillVersion]:
    stmt = select(SkillVersion).where(SkillVersion.skill_id == skill_id)
    if not include_deprecated:
        stmt = stmt.where(SkillVersion.lifecycle_status != "deprecated")
    stmt = stmt.order_by(SkillVersion.id.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def deactivate_others(
    session: AsyncSession, skill_id: int, keep_version_id: int
) -> None:
    """将同一 Skill 中其它 is_active 版本降为非 active（保留 lifecycle_status）。

    published 是生命周期阶段，可多版本共存（历史发布）；is_active 是单指针（当前生效）。
    只翻 is_active=False，不降级 lifecycle_status，以维持部分唯一索引
    uq_skill_versions_active 的单 active 不变式，且让 Yank 能重算到次新 published。
    必须在 set_active 之前调用。
    """
    await session.execute(
        update(SkillVersion)
        .where(
            SkillVersion.skill_id == skill_id,
            SkillVersion.id != keep_version_id,
            SkillVersion.is_active == True,  # noqa: E712
        )
        .values(is_active=False)
    )


async def set_active(session: AsyncSession, version_id: int) -> None:
    await session.execute(
        update(SkillVersion)
        .where(SkillVersion.id == version_id)
        .values(is_active=True, lifecycle_status="published")
    )


async def set_active_with_lock(
    session: AsyncSession, version_id: int, expected_lock_version: int
) -> None:
    """乐观锁激活：lock_version 不匹配（被并发改）→ rowcount 0 → ConflictError。"""
    result = await session.execute(
        update(SkillVersion)
        .where(
            SkillVersion.id == version_id,
            SkillVersion.lock_version == expected_lock_version,
        )
        .values(
            is_active=True,
            lifecycle_status="published",
            lock_version=expected_lock_version + 1,
        )
    )
    if result.rowcount == 0:
        raise ConflictError("资源已被他人修改，请刷新重试")


async def mark_deprecated(
    session: AsyncSession, version_id: int, sunset_date: datetime | None
) -> None:
    await session.execute(
        update(SkillVersion)
        .where(SkillVersion.id == version_id)
        .values(lifecycle_status="deprecated", sunset_date=sunset_date)
    )


async def mark_deprecated_with_lock(
    session: AsyncSession,
    version_id: int,
    sunset_date: datetime | None,
    expected_lock_version: int,
) -> None:
    """乐观锁弃用：lock_version 不匹配 → ConflictError。"""
    result = await session.execute(
        update(SkillVersion)
        .where(
            SkillVersion.id == version_id,
            SkillVersion.lock_version == expected_lock_version,
        )
        .values(
            lifecycle_status="deprecated",
            sunset_date=sunset_date,
            lock_version=expected_lock_version + 1,
        )
    )
    if result.rowcount == 0:
        raise ConflictError("资源已被他人修改，请刷新重试")


async def update_security_status(
    session: AsyncSession,
    version_id: int,
    *,
    status: str,
    decision: str,
    severity: str,
    risk_score: int,
    audit_id: int | None,
) -> None:
    """版本绑定安全审查结果回写。"""
    await session.execute(
        update(SkillVersion)
        .where(SkillVersion.id == version_id)
        .values(
            security_status=status,
            security_decision=decision,
            security_severity=severity,
            security_risk_score=risk_score,
            latest_ai_policies_audit_id=audit_id,
        )
    )


# ─── Drift detection (S9) ────────────────────────────────────────────────────


async def list_url_active(
    session: AsyncSession, limit: int = 100
) -> list[SkillVersion]:
    """所有 source_type='url' 且 lifecycle_status='published' 的版本。

    从未检测的（last_drift_check_at IS NULL）优先，其次按最早检测时间，
    确保长期未检查的版本先被扫描。limit 控制单批扫描量。
    """
    stmt = (
        select(SkillVersion)
        .where(
            SkillVersion.source_type == "url",
            SkillVersion.lifecycle_status == "published",
        )
        .order_by(SkillVersion.last_drift_check_at.asc().nullsfirst())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_drift_status(
    session: AsyncSession,
    version_id: int,
    *,
    drift_detected: bool,
    drifted_files: list[str],
    check_error: str = "",
) -> None:
    """回写漂移检测结果。check_error 非空表示本次拉取失败（此时 drift_detected 应为 False）。"""
    await session.execute(
        update(SkillVersion)
        .where(SkillVersion.id == version_id)
        .values(
            drift_detected=drift_detected,
            drifted_files=drifted_files,
            drift_check_error=check_error,
            last_drift_check_at=datetime.now(timezone.utc),
        )
    )


async def find_next_version_candidate(
    session: AsyncSession, skill_id: int, candidate: str
) -> SkillVersion | None:
    """查询候选版本号是否已被占用（resync 自动 bump 冲突重试用）。"""
    return await find_by_skill_and_version(session, skill_id, candidate)
