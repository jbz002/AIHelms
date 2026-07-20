"""评分 service。upsert + 事务内重算聚合；跨实体通用。"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError, ValidationError
from models.entity_types import FEEDBACK_TYPES, MCP_SERVER, RATABLE_ENTITY_TYPES, SKILL
from repositories import mcp_repo, rating_repo, skill_repo

logger = logging.getLogger(__name__)


async def _assert_entity_exists(
    session: AsyncSession, entity_type: str, entity_id: int
) -> None:
    if entity_type == MCP_SERVER:
        if await mcp_repo.find_server_by_id(session, entity_id) is None:
            raise NotFoundError("mcp_server", entity_id)
    elif entity_type == SKILL:
        if await skill_repo.find_by_id(session, entity_id) is None:
            raise NotFoundError("skill", entity_id)
    else:
        raise ValidationError(f"不支持的资源类型: {entity_type}")


async def rate(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
    user_id: int,
    score: int,
    feedback_type: str = "",
    comment: str = "",
) -> dict:
    if entity_type not in RATABLE_ENTITY_TYPES:
        raise ValidationError(f"不支持的资源类型: {entity_type}")
    if not isinstance(score, int) or not 1 <= score <= 5:
        raise ValidationError("评分必须在 1-5 之间")
    if feedback_type not in FEEDBACK_TYPES:
        raise ValidationError("无效的反馈分类")

    await _assert_entity_exists(session, entity_type, entity_id)

    try:
        await rating_repo.upsert_rating(
            session, entity_type, entity_id, user_id, score, feedback_type, comment
        )
        stats = await rating_repo.recompute_stats(session, entity_type, entity_id)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return {
        "my_score": score,
        "feedback_type": feedback_type,
        "avg_score": float(stats.avg_score),
        "rating_count": stats.rating_count,
    }


async def get_rating_view(
    session: AsyncSession, entity_type: str, entity_id: int, user_id: int
) -> dict:
    stats = await rating_repo.get_stats(session, entity_type, entity_id)
    mine = await rating_repo.find_my_rating(session, entity_type, entity_id, user_id)
    distribution = await rating_repo.get_score_distribution(
        session, entity_type, entity_id
    )
    avg_score = float(stats.avg_score) if stats else 0.0
    rating_count = stats.rating_count if stats else 0
    return {
        "avg_score": round(avg_score, 2),
        "rating_count": rating_count,
        "last_rated_at": (
            stats.last_rated_at.isoformat() if stats and stats.last_rated_at else None
        ),
        "my_score": mine.score if mine else None,
        "my_feedback_type": mine.feedback_type if mine else None,
        "my_comment": mine.comment if mine else None,
        "distribution": distribution,
    }


async def list_feedbacks(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
    feedback_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    items, total = await rating_repo.list_ratings(
        session, entity_type, entity_id, feedback_type, page, page_size
    )
    return {
        "items": [
            {
                "user_id": item.user_id,
                "score": item.score,
                "feedback_type": item.feedback_type,
                "comment": item.comment,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def enrich_items_with_ratings(
    session: AsyncSession, entity_type: str, items: list[dict]
) -> None:
    """就地给序列化项加 avg_score / rating_count（批量读防 N+1）。"""
    ids = [int(item["id"]) for item in items if item.get("id") is not None]
    stats_map = await rating_repo.find_stats_batch(session, entity_type, ids)
    for item in items:
        entity_id = int(item["id"]) if item.get("id") is not None else None
        avg, count = stats_map.get(entity_id, (0.0, 0))
        item["avg_score"] = round(avg, 2)
        item["rating_count"] = count
