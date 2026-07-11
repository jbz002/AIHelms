from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import McpServerVersion


async def create(session: AsyncSession, version: McpServerVersion) -> McpServerVersion:
    session.add(version)
    await session.flush()
    await session.refresh(version)
    return version


async def find_by_id(session: AsyncSession, version_id: int) -> McpServerVersion | None:
    result = await session.execute(
        select(McpServerVersion).where(McpServerVersion.id == version_id)
    )
    return result.scalar_one_or_none()


async def find_active_for_server(
    session: AsyncSession, server_id: int
) -> McpServerVersion | None:
    result = await session.execute(
        select(McpServerVersion).where(
            McpServerVersion.server_id == server_id,
            McpServerVersion.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def find_by_server_and_version(
    session: AsyncSession, server_id: int, version: str
) -> McpServerVersion | None:
    result = await session.execute(
        select(McpServerVersion).where(
            McpServerVersion.server_id == server_id,
            McpServerVersion.version == version,
        )
    )
    return result.scalar_one_or_none()


async def list_versions(
    session: AsyncSession,
    server_id: int,
    include_deprecated: bool = True,
) -> list[McpServerVersion]:
    stmt = select(McpServerVersion).where(McpServerVersion.server_id == server_id)
    if not include_deprecated:
        stmt = stmt.where(McpServerVersion.lifecycle_status != "deprecated")
    stmt = stmt.order_by(McpServerVersion.id.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def deactivate_others(
    session: AsyncSession, server_id: int, keep_version_id: int
) -> None:
    """将同一 Server 中其它处于 active 生命周期的版本降级为 inactive。

    只降级 lifecycle_status='active' 的行，不触碰 deprecated 行。
    必须在 set_active 之前调用，以维持部分唯一索引 uq_*_active 的单 active 不变式。
    """
    await session.execute(
        update(McpServerVersion)
        .where(
            McpServerVersion.server_id == server_id,
            McpServerVersion.id != keep_version_id,
            McpServerVersion.lifecycle_status == "active",
        )
        .values(is_active=False, lifecycle_status="inactive")
    )


async def set_active(session: AsyncSession, version_id: int) -> None:
    await session.execute(
        update(McpServerVersion)
        .where(McpServerVersion.id == version_id)
        .values(is_active=True, lifecycle_status="active")
    )


async def mark_deprecated(
    session: AsyncSession, version_id: int, sunset_date: datetime | None
) -> None:
    await session.execute(
        update(McpServerVersion)
        .where(McpServerVersion.id == version_id)
        .values(lifecycle_status="deprecated", sunset_date=sunset_date)
    )
