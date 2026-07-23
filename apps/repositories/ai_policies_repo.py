from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import AiPoliciesAudit, AiPoliciesRiskCatalog, AiPoliciesSettings


async def create_audit(
    session: AsyncSession, audit: AiPoliciesAudit
) -> AiPoliciesAudit:
    session.add(audit)
    await session.flush()
    await session.refresh(audit)
    return audit


async def find_by_id(session: AsyncSession, audit_id: int) -> AiPoliciesAudit | None:
    result = await session.execute(
        select(AiPoliciesAudit).where(AiPoliciesAudit.id == audit_id)
    )
    return result.scalar_one_or_none()


async def find_by_audit_id(
    session: AsyncSession, audit_id: str
) -> AiPoliciesAudit | None:
    result = await session.execute(
        select(AiPoliciesAudit).where(AiPoliciesAudit.audit_id == audit_id)
    )
    return result.scalar_one_or_none()


async def find_by_ids(
    session: AsyncSession, audit_ids: list[int]
) -> list[AiPoliciesAudit]:
    if not audit_ids:
        return []
    result = await session.execute(
        select(AiPoliciesAudit).where(AiPoliciesAudit.id.in_(audit_ids))
    )
    return list(result.scalars().all())


async def find_active_by_skill(
    session: AsyncSession, skill_id: int
) -> AiPoliciesAudit | None:
    result = await session.execute(
        select(AiPoliciesAudit)
        .where(
            AiPoliciesAudit.audit_type == "skill",
            AiPoliciesAudit.skill_id == skill_id,
            AiPoliciesAudit.status.in_(["queued", "running"]),
        )
        .order_by(AiPoliciesAudit.created_at.desc(), AiPoliciesAudit.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_active_by_entity(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
) -> AiPoliciesAudit | None:
    result = await session.execute(
        select(AiPoliciesAudit)
        .where(
            AiPoliciesAudit.entity_type == entity_type,
            AiPoliciesAudit.entity_id == entity_id,
            AiPoliciesAudit.status.in_(["queued", "running"]),
        )
        .order_by(AiPoliciesAudit.created_at.desc(), AiPoliciesAudit.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _apply_filters(
    stmt,
    audit_type: str | None = None,
    skill_id: int | None = None,
    status: str | None = None,
    decision: str | None = None,
    q: str | None = None,
    finished_from: datetime | None = None,
    finished_to: datetime | None = None,
    unfinished: bool | None = None,
):
    if audit_type:
        stmt = stmt.where(AiPoliciesAudit.audit_type == audit_type)
    if skill_id:
        stmt = stmt.where(AiPoliciesAudit.skill_id == skill_id)
    if status:
        stmt = stmt.where(AiPoliciesAudit.status == status)
    if decision:
        stmt = stmt.where(AiPoliciesAudit.decision == decision)
    if q:
        stmt = stmt.where(AiPoliciesAudit.skill_name.ilike(f"%{q}%"))
    if unfinished is True:
        stmt = stmt.where(AiPoliciesAudit.finished_at.is_(None))
    elif unfinished is False:
        stmt = stmt.where(AiPoliciesAudit.finished_at.is_not(None))
    if finished_from:
        stmt = stmt.where(AiPoliciesAudit.finished_at >= finished_from)
    if finished_to:
        stmt = stmt.where(AiPoliciesAudit.finished_at <= finished_to)
    return stmt


async def find_all(
    session: AsyncSession,
    page: int,
    page_size: int,
    audit_type: str | None = None,
    skill_id: int | None = None,
    status: str | None = None,
    decision: str | None = None,
    q: str | None = None,
    finished_from: datetime | None = None,
    finished_to: datetime | None = None,
    unfinished: bool | None = None,
) -> list[AiPoliciesAudit]:
    stmt = select(AiPoliciesAudit).order_by(
        AiPoliciesAudit.created_at.desc(), AiPoliciesAudit.id.desc()
    )
    stmt = _apply_filters(
        stmt,
        audit_type,
        skill_id,
        status,
        decision,
        q,
        finished_from,
        finished_to,
        unfinished,
    )
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_all(
    session: AsyncSession,
    audit_type: str | None = None,
    skill_id: int | None = None,
    status: str | None = None,
    decision: str | None = None,
    q: str | None = None,
    finished_from: datetime | None = None,
    finished_to: datetime | None = None,
    unfinished: bool | None = None,
) -> int:
    stmt = select(func.count(AiPoliciesAudit.id))
    stmt = _apply_filters(
        stmt,
        audit_type,
        skill_id,
        status,
        decision,
        q,
        finished_from,
        finished_to,
        unfinished,
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def list_catalog(session: AsyncSession) -> list[AiPoliciesRiskCatalog]:
    result = await session.execute(
        select(AiPoliciesRiskCatalog).order_by(AiPoliciesRiskCatalog.sort_order)
    )
    return list(result.scalars().all())


async def get_settings(session: AsyncSession) -> AiPoliciesSettings:
    settings = await session.get(AiPoliciesSettings, 1)
    if settings:
        return settings
    settings = AiPoliciesSettings(id=1)
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


async def next_scan_round(
    session: AsyncSession,
    skill_id: int,
    skill_version_id: int | None,
) -> int:
    """同 skill + version 的下一轮扫描序号（max(scan_round)+1）。

    并发安全由 find_active_by_skill 阻同 version 并发审查保证。
    skill_version_id 为 None 时匹配主表级审查。
    """
    version_filter = (
        AiPoliciesAudit.skill_version_id == skill_version_id
        if skill_version_id is not None
        else AiPoliciesAudit.skill_version_id.is_(None)
    )
    result = await session.execute(
        select(func.max(AiPoliciesAudit.scan_round)).where(
            AiPoliciesAudit.skill_id == skill_id,
            version_filter,
        )
    )
    current = result.scalar()
    return (current or 0) + 1


async def mark_audits_deleted_for_skill(session: AsyncSession, skill_id: int) -> None:
    """Skill 物理删除时，关联审计行 soft-delete（deleted_at 标记，不删行）。

    同时把将悬空的 skill_id / skill_version_id 置 NULL：Skill 物理删除后这两个外键
    必然失效，预先在此 UPDATE 里清空，避免「先 UPDATE 审计行 → 再级联删版本」时
    PG 对刚被改动的行复检外键、发现版本已删而抛 ForeignKeyViolationError。
    """
    await session.execute(
        update(AiPoliciesAudit)
        .where(
            AiPoliciesAudit.skill_id == skill_id,
            AiPoliciesAudit.deleted_at.is_(None),
        )
        .values(deleted_at=func.now(), skill_id=None, skill_version_id=None)
    )


async def list_audit_history(
    session: AsyncSession,
    skill_id: int,
    skill_version_id: int,
    page: int,
    page_size: int,
) -> list[AiPoliciesAudit]:
    """按版本查扫描历史（scan_round 倒序，排除 soft-delete，轻量字段）。"""
    stmt = (
        select(
            AiPoliciesAudit.id,
            AiPoliciesAudit.audit_id,
            AiPoliciesAudit.status,
            AiPoliciesAudit.decision,
            AiPoliciesAudit.verdict,
            AiPoliciesAudit.policy,
            AiPoliciesAudit.severity,
            AiPoliciesAudit.risk_score,
            AiPoliciesAudit.findings_count,
            AiPoliciesAudit.high_risk_count,
            AiPoliciesAudit.must_review_count,
            AiPoliciesAudit.scan_round,
            AiPoliciesAudit.llm_review_used,
            AiPoliciesAudit.created_at,
            AiPoliciesAudit.finished_at,
        )
        .where(
            AiPoliciesAudit.skill_id == skill_id,
            AiPoliciesAudit.skill_version_id == skill_version_id,
            AiPoliciesAudit.deleted_at.is_(None),
        )
        .order_by(AiPoliciesAudit.scan_round.desc(), AiPoliciesAudit.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await session.execute(stmt)
    return list(result.all())


async def count_audit_history(
    session: AsyncSession,
    skill_id: int,
    skill_version_id: int,
) -> int:
    result = await session.execute(
        select(func.count(AiPoliciesAudit.id)).where(
            AiPoliciesAudit.skill_id == skill_id,
            AiPoliciesAudit.skill_version_id == skill_version_id,
            AiPoliciesAudit.deleted_at.is_(None),
        )
    )
    return result.scalar_one()
