"""存储删除补偿 repository。

DB 事务提交后删文件失败 → 写补偿记录；Celery 定时重试，达上限标 failed。
"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import StorageDeletionCompensation


async def create(
    session: AsyncSession,
    *,
    entity_type: str,
    storage_path: str,
    entity_id: int | None = None,
    last_error: str = "",
) -> StorageDeletionCompensation:
    comp = StorageDeletionCompensation(
        entity_type=entity_type,
        entity_id=entity_id,
        storage_path=storage_path,
        status="pending",
        last_error=last_error,
    )
    session.add(comp)
    await session.flush()
    await session.refresh(comp)
    return comp


async def list_pending(
    session: AsyncSession, limit: int = 100
) -> list[StorageDeletionCompensation]:
    result = await session.execute(
        select(StorageDeletionCompensation)
        .where(StorageDeletionCompensation.status == "pending")
        .order_by(StorageDeletionCompensation.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_all(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
) -> tuple[list[StorageDeletionCompensation], int]:
    base = select(StorageDeletionCompensation)
    if status:
        base = base.where(StorageDeletionCompensation.status == status)
    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    offset = (page - 1) * page_size
    stmt = (
        base.order_by(StorageDeletionCompensation.created_at.desc())
        .limit(page_size)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), int(total)


async def mark_done(session: AsyncSession, comp_id: int) -> None:
    from datetime import datetime, timezone

    await session.execute(
        update(StorageDeletionCompensation)
        .where(StorageDeletionCompensation.id == comp_id)
        .values(status="done", completed_at=datetime.now(timezone.utc), last_error="")
    )


async def inc_retry(
    session: AsyncSession, comp_id: int, error: str, max_retries: int
) -> str:
    """递增重试计数；达上限标 failed，否则保持 pending。返回新状态。"""
    new_retries = StorageDeletionCompensation.retries + 1
    res_failed = await session.execute(
        update(StorageDeletionCompensation)
        .where(
            StorageDeletionCompensation.id == comp_id,
            StorageDeletionCompensation.retries + 1 >= max_retries,
        )
        .values(status="failed", last_error=error, retries=new_retries)
    )
    if res_failed.rowcount > 0:
        return "failed"
    await session.execute(
        update(StorageDeletionCompensation)
        .where(StorageDeletionCompensation.id == comp_id)
        .values(status="pending", last_error=error, retries=new_retries)
    )
    return "pending"
