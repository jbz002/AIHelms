"""授权矩阵 / 工具束 / 编译状态 / 策略版本的数据访问。"""

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import McpGrant, McpPolicyVersion, McpSyncState, McpToolset


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active_clause():
    return (
        McpGrant.revoked_at.is_(None),
        or_(McpGrant.expires_at.is_(None), McpGrant.expires_at > _now()),
    )


# ─── Grants ──────────────────────────────────────────────────────────────────


async def list_grants(
    session: AsyncSession,
    subject_type: str | None = None,
    subject_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    include_revoked: bool = False,
) -> list[McpGrant]:
    stmt = select(McpGrant).order_by(McpGrant.id.desc())
    if not include_revoked:
        for clause in _active_clause():
            stmt = stmt.where(clause)
    if subject_type is not None:
        stmt = stmt.where(McpGrant.subject_type == subject_type)
    if subject_id is not None:
        stmt = stmt.where(McpGrant.subject_id == subject_id)
    if target_type is not None:
        stmt = stmt.where(McpGrant.target_type == target_type)
    if target_id is not None:
        stmt = stmt.where(McpGrant.target_id == target_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_active_grant(
    session: AsyncSession,
    subject_type: str,
    subject_id: int | None,
    target_type: str,
    target_id: int,
) -> McpGrant | None:
    stmt = select(McpGrant).where(
        McpGrant.subject_type == subject_type,
        (
            McpGrant.subject_id.is_(None)
            if subject_id is None
            else McpGrant.subject_id == subject_id
        ),
        McpGrant.target_type == target_type,
        McpGrant.target_id == target_id,
    )
    for clause in _active_clause():
        stmt = stmt.where(clause)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def find_grants_for_subjects(
    session: AsyncSession, subjects: list[tuple[str, int | None]]
) -> list[McpGrant]:
    """一次取回若干主体的全部生效授权（编译热路径：每人 1 次查询）。"""
    if not subjects:
        return []
    clauses = []
    for subject_type, subject_id in subjects:
        if subject_id is None:
            clauses.append(
                (McpGrant.subject_type == subject_type)
                & (McpGrant.subject_id.is_(None))
            )
        else:
            clauses.append(
                (McpGrant.subject_type == subject_type)
                & (McpGrant.subject_id == subject_id)
            )
    stmt = select(McpGrant).where(or_(*clauses))
    for clause in _active_clause():
        stmt = stmt.where(clause)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_grant(session: AsyncSession, grant: McpGrant) -> McpGrant:
    session.add(grant)
    await session.flush()
    await session.refresh(grant)
    return grant


async def revoke_grant(
    session: AsyncSession, grant: McpGrant, revoked_by: int | None = None
) -> None:
    grant.revoked_at = _now()
    grant.revoked_by = revoked_by
    await session.flush()


# ─── Toolsets ────────────────────────────────────────────────────────────────


async def list_toolsets(session: AsyncSession) -> list[McpToolset]:
    result = await session.execute(select(McpToolset).order_by(McpToolset.id))
    return list(result.scalars().all())


async def find_toolset_by_id(
    session: AsyncSession, toolset_id: int
) -> McpToolset | None:
    return await session.get(McpToolset, toolset_id)


async def find_toolset_by_name(session: AsyncSession, name: str) -> McpToolset | None:
    result = await session.execute(select(McpToolset).where(McpToolset.name == name))
    return result.scalar_one_or_none()


async def create_toolset(session: AsyncSession, toolset: McpToolset) -> McpToolset:
    session.add(toolset)
    await session.flush()
    await session.refresh(toolset)
    return toolset


async def delete_toolset(session: AsyncSession, toolset: McpToolset) -> None:
    await session.delete(toolset)
    await session.flush()


# ─── Sync state ──────────────────────────────────────────────────────────────


async def get_sync_state(session: AsyncSession, ai_key_id: int) -> McpSyncState | None:
    return await session.get(McpSyncState, ai_key_id)


async def upsert_sync_state(
    session: AsyncSession,
    ai_key_id: int,
    input_hash: str | None = None,
    applied_hash: str | None = None,
    status: str = "synced",
    error_code: str | None = None,
) -> McpSyncState:
    state = await session.get(McpSyncState, ai_key_id)
    if state is None:
        state = McpSyncState(ai_key_id=ai_key_id)
        session.add(state)
    state.input_hash = input_hash
    state.applied_hash = applied_hash
    state.status = status
    state.error_code = error_code
    if status == "synced":
        state.synced_at = _now()
    await session.flush()
    return state


# ─── Policy versions ─────────────────────────────────────────────────────────


async def current_policy_version(session: AsyncSession) -> int:
    result = await session.execute(select(func.max(McpPolicyVersion.version)))
    return int(result.scalar() or 0)


async def bump_policy_version(
    session: AsyncSession, changed_by: int | None, summary: str
) -> int:
    version = await current_policy_version(session) + 1
    session.add(
        McpPolicyVersion(
            version=version, changed_by=changed_by, change_summary=summary[:500]
        )
    )
    await session.flush()
    return version
