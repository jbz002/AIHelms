"""评分 repository。

手动 lookup-then-update-or-create（无 ON CONFLICT），聚合走 text()。
"""

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError
from models.db import EntityRating, EntityRatingStats


async def find_my_rating(
    session: AsyncSession, entity_type: str, entity_id: int, user_id: int
) -> EntityRating | None:
    result = await session.execute(
        select(EntityRating).where(
            EntityRating.entity_type == entity_type,
            EntityRating.entity_id == entity_id,
            EntityRating.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_rating(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
    user_id: int,
    score: int,
    feedback_type: str = "",
    comment: str = "",
) -> EntityRating:
    existing = await find_my_rating(session, entity_type, entity_id, user_id)
    if existing:
        result = await session.execute(
            update(EntityRating)
            .where(
                EntityRating.id == existing.id,
                EntityRating.lock_version == existing.lock_version,
            )
            .values(
                score=score,
                feedback_type=feedback_type,
                comment=comment,
                lock_version=existing.lock_version + 1,
            )
        )
        if result.rowcount == 0:
            raise ConflictError("评分已被他人修改，请刷新重试")
        await session.refresh(existing)
        return existing

    rating = EntityRating(
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        score=score,
        feedback_type=feedback_type,
        comment=comment,
    )
    session.add(rating)
    await session.flush()
    await session.refresh(rating)
    return rating


async def count_ratings(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
    feedback_type: str | None = None,
) -> int:
    stmt = select(func.count(EntityRating.id)).where(
        EntityRating.entity_type == entity_type,
        EntityRating.entity_id == entity_id,
    )
    if feedback_type:
        stmt = stmt.where(EntityRating.feedback_type == feedback_type)
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def list_ratings(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
    feedback_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EntityRating], int]:
    total = await count_ratings(session, entity_type, entity_id, feedback_type)
    stmt = (
        select(EntityRating)
        .where(
            EntityRating.entity_type == entity_type,
            EntityRating.entity_id == entity_id,
        )
        .order_by(EntityRating.updated_at.desc())
    )
    if feedback_type:
        stmt = stmt.where(EntityRating.feedback_type == feedback_type)
    offset = (page - 1) * page_size
    stmt = stmt.limit(page_size).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_stats(
    session: AsyncSession, entity_type: str, entity_id: int
) -> EntityRatingStats | None:
    result = await session.execute(
        select(EntityRatingStats).where(
            EntityRatingStats.entity_type == entity_type,
            EntityRatingStats.entity_id == entity_id,
        )
    )
    return result.scalar_one_or_none()


async def find_stats_batch(
    session: AsyncSession, entity_type: str, ids: list[int]
) -> dict[int, tuple[float, int]]:
    """批量读评分聚合，供市场卡片避免 N+1。缺失 id 不在返回 dict 中。"""
    if not ids:
        return {}
    sql = text(
        "SELECT entity_id, avg_score, rating_count "
        "FROM aihelms.entity_rating_stats "
        "WHERE entity_type = :t AND entity_id = ANY(:ids)"
    )
    result = await session.execute(sql, {"t": entity_type, "ids": ids})
    return {
        int(row.entity_id): (float(row.avg_score), int(row.rating_count))
        for row in result.fetchall()
    }


async def get_score_distribution(
    session: AsyncSession, entity_type: str, entity_id: int
) -> dict[int, int]:
    sql = text(
        "SELECT score, COUNT(*) AS cnt "
        "FROM aihelms.entity_ratings "
        "WHERE entity_type = :t AND entity_id = :id "
        "GROUP BY score"
    )
    result = await session.execute(sql, {"t": entity_type, "id": entity_id})
    distribution = {star: 0 for star in range(1, 6)}
    for row in result.fetchall():
        distribution[int(row.score)] = int(row.cnt)
    return distribution


async def recompute_stats(
    session: AsyncSession, entity_type: str, entity_id: int
) -> EntityRatingStats:
    """重算 avg/count 写聚合表（手动 upsert stats 行）。只 flush，由 service 提交。"""
    agg_sql = text(
        "SELECT COUNT(*) AS cnt, "
        "COALESCE(AVG(score), 0)::numeric(3,2) AS avg_score, "
        "MAX(updated_at) AS last_rated_at "
        "FROM aihelms.entity_ratings "
        "WHERE entity_type = :t AND entity_id = :id"
    )
    row = (await session.execute(agg_sql, {"t": entity_type, "id": entity_id})).one()

    stats = await get_stats(session, entity_type, entity_id)
    if stats is None:
        stats = EntityRatingStats(
            entity_type=entity_type,
            entity_id=entity_id,
            avg_score=row.avg_score,
            rating_count=int(row.cnt),
            last_rated_at=row.last_rated_at,
        )
        session.add(stats)
    else:
        stats.avg_score = row.avg_score
        stats.rating_count = int(row.cnt)
        stats.last_rated_at = row.last_rated_at
    await session.flush()
    await session.refresh(stats)
    return stats
