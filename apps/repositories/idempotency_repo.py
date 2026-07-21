"""幂等记录 repository。

DB 为幂等性持久化源（Redis 仅加速抢锁防并发，Redis 重启不丢幂等性）。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import IdempotencyRecord


async def find_by_key(session: AsyncSession, key: str) -> IdempotencyRecord | None:
    result = await session.execute(
        select(IdempotencyRecord).where(IdempotencyRecord.key == key)
    )
    return result.scalar_one_or_none()


async def upsert_record(
    session: AsyncSession,
    *,
    key: str,
    entity_type: str,
    request_hash: str,
    ttl_hours: int,
) -> tuple[IdempotencyRecord, bool]:
    """插入幂等记录。命中既有 key（ON CONFLICT nothing）→ 返回 (record, False)。

    entity_type 用于溯源；entity_id 留空（写接口返回前无法稳定拿到）。
    """
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    stmt = pg_insert(IdempotencyRecord).values(
        key=key,
        entity_type=entity_type,
        request_hash=request_hash,
        expires_at=expires_at,
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["key"])
    result = await session.execute(stmt)
    created = result.rowcount == 1
    await session.commit()
    record = await find_by_key(session, key)
    assert record is not None  # on_conflict_do_nothing 后行必定存在
    return record, created


async def save_response(
    session: AsyncSession,
    record_id: int,
    response_code: int,
    response_body: dict | None,
) -> None:
    record = await session.get(IdempotencyRecord, record_id)
    if record is None:
        return
    record.response_code = response_code
    record.response_body = response_body
    await session.commit()


async def cleanup_expired(session: AsyncSession) -> int:
    """删除过期记录（供定时任务调用）。"""
    from sqlalchemy import delete

    now = datetime.now(timezone.utc)
    result = await session.execute(
        delete(IdempotencyRecord).where(IdempotencyRecord.expires_at < now)
    )
    await session.commit()
    return result.rowcount
