from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    """将同一 Skill 中其它处于 active 生命周期的版本降级为 inactive。

    只降级 lifecycle_status='active' 的行，不触碰 deprecated 行。
    必须在 set_active 之前调用，以维持部分唯一索引 uq_skill_versions_active
    的单 active 不变式。
    """
    await session.execute(
        update(SkillVersion)
        .where(
            SkillVersion.skill_id == skill_id,
            SkillVersion.id != keep_version_id,
            SkillVersion.lifecycle_status == "active",
        )
        .values(is_active=False, lifecycle_status="inactive")
    )


async def set_active(session: AsyncSession, version_id: int) -> None:
    await session.execute(
        update(SkillVersion)
        .where(SkillVersion.id == version_id)
        .values(is_active=True, lifecycle_status="active")
    )


async def mark_deprecated(
    session: AsyncSession, version_id: int, sunset_date: datetime | None
) -> None:
    await session.execute(
        update(SkillVersion)
        .where(SkillVersion.id == version_id)
        .values(lifecycle_status="deprecated", sunset_date=sunset_date)
    )


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
