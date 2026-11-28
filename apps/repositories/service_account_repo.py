"""服务账号与委托授权的数据访问（P2）。"""

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import DelegationGrant, ServiceAccount


def _now() -> datetime:
    return datetime.now(timezone.utc)


def delegation_active_clause():
    """生效中的委托：未撤销且未过期。"""
    return (
        DelegationGrant.revoked_at.is_(None),
        or_(
            DelegationGrant.expires_at.is_(None),
            DelegationGrant.expires_at > _now(),
        ),
    )


# ─── 服务账号 ────────────────────────────────────────────────────────────────


async def list_service_accounts(session: AsyncSession) -> list[ServiceAccount]:
    result = await session.execute(select(ServiceAccount).order_by(ServiceAccount.id))
    return list(result.scalars().all())


async def find_by_id(session: AsyncSession, sa_id: int) -> ServiceAccount | None:
    return await session.get(ServiceAccount, sa_id)


async def find_by_name(session: AsyncSession, name: str) -> ServiceAccount | None:
    result = await session.execute(
        select(ServiceAccount).where(ServiceAccount.name == name)
    )
    return result.scalars().first()


async def find_by_token_hash(
    session: AsyncSession, token_hash: str
) -> ServiceAccount | None:
    result = await session.execute(
        select(ServiceAccount).where(ServiceAccount.token_hash == token_hash)
    )
    return result.scalars().first()


async def create(session: AsyncSession, sa: ServiceAccount) -> ServiceAccount:
    session.add(sa)
    await session.flush()
    await session.refresh(sa)
    return sa


async def delete(session: AsyncSession, sa: ServiceAccount) -> None:
    await session.delete(sa)


# ─── 委托授权 ────────────────────────────────────────────────────────────────


async def list_delegations(
    session: AsyncSession,
    service_account_id: int | None = None,
    user_id: int | None = None,
    include_revoked: bool = False,
) -> list[DelegationGrant]:
    stmt = select(DelegationGrant).order_by(DelegationGrant.id.desc())
    if not include_revoked:
        for clause in delegation_active_clause():
            stmt = stmt.where(clause)
    if service_account_id is not None:
        stmt = stmt.where(DelegationGrant.service_account_id == service_account_id)
    if user_id is not None:
        stmt = stmt.where(DelegationGrant.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_delegation_by_id(
    session: AsyncSession, grant_id: int
) -> DelegationGrant | None:
    return await session.get(DelegationGrant, grant_id)


async def find_active_delegation(
    session: AsyncSession,
    service_account_id: int,
    user_id: int,
    target_type: str,
    target_id: int,
) -> DelegationGrant | None:
    stmt = select(DelegationGrant).where(
        DelegationGrant.service_account_id == service_account_id,
        DelegationGrant.user_id == user_id,
        DelegationGrant.target_type == target_type,
        DelegationGrant.target_id == target_id,
        *delegation_active_clause(),
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def active_delegations_for(
    session: AsyncSession, service_account_id: int, user_id: int
) -> list[DelegationGrant]:
    stmt = select(DelegationGrant).where(
        DelegationGrant.service_account_id == service_account_id,
        DelegationGrant.user_id == user_id,
        *delegation_active_clause(),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_delegation(
    session: AsyncSession, grant: DelegationGrant
) -> DelegationGrant:
    session.add(grant)
    await session.flush()
    await session.refresh(grant)
    return grant


async def revoke_delegation(
    session: AsyncSession, grant: DelegationGrant, revoked_by: int | None = None
) -> None:
    grant.revoked_at = _now()
    grant.revoked_by = revoked_by
    await session.flush()
