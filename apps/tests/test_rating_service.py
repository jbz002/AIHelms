"""评分 service 集成测试（走真实 DB，依赖 dev 中间件运行）。

覆盖：upsert 幂等、recompute_stats 正确性、非法 score/type、缺失实体、
find_stats_batch、enrich。
"""

import uuid

import pytest
from sqlalchemy import delete, select

from core.database import get_worker_session_factory
from exceptions import NotFoundError, ValidationError
from models.db import EntityRating, EntityRatingStats, Skill, SkillVersion, User
from repositories import rating_repo
from services import rating_service, skill_service


def _session():
    return get_worker_session_factory()()


async def _real_user_id() -> int:
    async with _session() as s:
        result = await s.execute(select(User.id).limit(1))
        row = result.scalar_one_or_none()
        assert row is not None, "测试需至少一个真实用户"
        return int(row)


async def _make_skill() -> int:
    name = f"test_rating_{uuid.uuid4().hex[:8]}"
    session = _session()
    try:
        data = await skill_service.create_skill(
            session,
            name=name,
            version="1.0.0",
            zip_content=b"PK\x03\x04fake",
            zip_filename=f"{name}.zip",
        )
    finally:
        await session.close()
    return int(data["id"])


async def _cleanup_skill(skill_id: int) -> None:
    async with _session() as s:
        await s.execute(delete(EntityRating).where(EntityRating.entity_id == skill_id))
        await s.execute(
            delete(EntityRatingStats).where(EntityRatingStats.entity_id == skill_id)
        )
        await s.execute(delete(SkillVersion).where(SkillVersion.skill_id == skill_id))
        await s.execute(delete(Skill).where(Skill.id == skill_id))
        await s.commit()


@pytest.mark.asyncio
async def test_rate_creates_then_updates_idempotent():
    skill_id = await _make_skill()
    user_id = await _real_user_id()
    try:
        session = _session()
        await rating_service.rate(
            session, "skill", skill_id, user_id, score=3, comment="first"
        )
        await session.close()

        session = _session()
        await rating_service.rate(
            session, "skill", skill_id, user_id, score=5, comment="second"
        )
        await session.close()

        async with _session() as s:
            rows = await rating_repo.list_ratings(s, "skill", skill_id)
            items, total = rows
            assert total == 1
            assert items[0].score == 5
            assert items[0].comment == "second"
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_recompute_stats_correct_after_multiple_ratings():
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            users = (await s.execute(select(User.id).limit(3))).scalars().all()
            assert len(users) >= 3, "测试需至少三个真实用户"
            for u, sc in zip(users, [5, 4, 3]):
                await rating_repo.upsert_rating(s, "skill", skill_id, int(u), sc)
            stats = await rating_repo.recompute_stats(s, "skill", skill_id)
            await s.commit()
            assert stats.rating_count == 3
            assert float(stats.avg_score) == 4.0
            assert stats.last_rated_at is not None
    finally:
        async with _session() as s:
            await s.execute(
                delete(EntityRating).where(EntityRating.entity_id == skill_id)
            )
            await s.commit()
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_recompute_stats_zero_when_no_ratings():
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            stats = await rating_repo.recompute_stats(s, "skill", skill_id)
            await s.commit()
            assert stats.rating_count == 0
            assert float(stats.avg_score) == 0.0
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_rate_rejects_invalid_score_and_type():
    skill_id = await _make_skill()
    user_id = await _real_user_id()
    try:
        for bad_score in (0, 6):
            session = _session()
            with pytest.raises(ValidationError):
                await rating_service.rate(
                    session, "skill", skill_id, user_id, score=bad_score
                )
            await session.close()

        session = _session()
        with pytest.raises(ValidationError):
            await rating_service.rate(session, "agent", skill_id, user_id, score=5)
        await session.close()

        session = _session()
        with pytest.raises(ValidationError):
            await rating_service.rate(
                session,
                "skill",
                skill_id,
                user_id,
                score=5,
                feedback_type="invalid",
            )
        await session.close()
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_rate_rejects_missing_entity():
    user_id = await _real_user_id()
    session = _session()
    with pytest.raises(NotFoundError):
        await rating_service.rate(session, "skill", 999999999, user_id, score=5)
    await session.close()


@pytest.mark.asyncio
async def test_find_stats_batch_returns_only_present():
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            await rating_repo.upsert_rating(
                s, "skill", skill_id, (await _real_user_id()), 4
            )
            await rating_repo.recompute_stats(s, "skill", skill_id)
            await s.commit()

        async with _session() as s:
            batch = await rating_repo.find_stats_batch(
                s, "skill", [skill_id, 999999999]
            )
            assert skill_id in batch
            assert 999999999 not in batch
            avg, count = batch[skill_id]
            assert count == 1
            assert avg == 4.0
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_enrich_items_with_ratings_adds_fields():
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            await rating_repo.upsert_rating(
                s, "skill", skill_id, (await _real_user_id()), 5
            )
            await rating_repo.recompute_stats(s, "skill", skill_id)
            await s.commit()

        async with _session() as s:
            items = [{"id": skill_id}, {"id": 999999999}]
            await rating_service.enrich_items_with_ratings(s, "skill", items)
            assert items[0]["avg_score"] == 5.0
            assert items[0]["rating_count"] == 1
            assert items[1]["avg_score"] == 0.0
            assert items[1]["rating_count"] == 0
    finally:
        await _cleanup_skill(skill_id)
