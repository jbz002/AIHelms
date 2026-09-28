"""发布评审 service 集成测试（走真实 DB，依赖 dev 中间件运行）。

覆盖：submit + 重复 pending 拦截、approve（is_published 生效）、reject（保持未发布）、
withdraw（非创建者/非 pending 拦截）、resolve_publish 门控开关。
"""

import uuid

import pytest
from sqlalchemy import delete, select

from core.database import get_worker_session_factory
from exceptions import ConflictError, ValidationError
from models.db import PublishReview, PublishSettings, Skill, SkillVersion, User
from services import publish_review_service, skill_service


def _session():
    return get_worker_session_factory()()


async def _real_user_id() -> int:
    async with _session() as s:
        result = await s.execute(select(User.id).limit(1))
        row = result.scalar_one_or_none()
        assert row is not None, "测试需至少一个真实用户"
        return int(row)


def _fake_zip_bytes() -> bytes:
    """合法 skill 包（含 SKILL.md，frontmatter name 为 kebab-case），过物理校验。"""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "pub-review-skill/SKILL.md",
            "---\nname: pub-review-skill\ndescription: test\n---\n# t\n\ntest body\n",
        )
    return buf.getvalue()


async def _make_skill() -> int:
    name = f"test-pub-{uuid.uuid4().hex[:8]}"
    session = _session()
    try:
        data = await skill_service.create_skill(
            session,
            name=name,
            version="1.0.0",
            zip_content=_fake_zip_bytes(),
            zip_filename=f"{name}.zip",
        )
    finally:
        await session.close()
    return int(data["id"])


async def _cleanup_skill(skill_id: int) -> None:
    async with _session() as s:
        await s.execute(
            delete(PublishReview).where(PublishReview.entity_id == skill_id)
        )
        await s.execute(delete(SkillVersion).where(SkillVersion.skill_id == skill_id))
        await s.execute(delete(Skill).where(Skill.id == skill_id))
        await s.commit()


async def _reset_gate(enabled: bool = False) -> None:
    async with _session() as s:
        settings = await s.get(PublishSettings, 1)
        assert settings is not None, "publish_settings 单例行缺失"
        settings.publish_review_enabled = enabled
        await s.commit()


@pytest.mark.asyncio
async def test_submit_creates_pending_and_blocks_duplicate():
    skill_id = await _make_skill()
    user_id = await _real_user_id()
    try:
        session = _session()
        review = await publish_review_service.submit_review(
            session, "skill", skill_id, user_id
        )
        await session.close()
        assert review.status == "pending"

        session = _session()
        with pytest.raises(ConflictError):
            await publish_review_service.submit_review(
                session, "skill", skill_id, user_id
            )
        await session.close()
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_approve_sets_published():
    skill_id = await _make_skill()
    user_id = await _real_user_id()
    try:
        session = _session()
        review = await publish_review_service.submit_review(
            session, "skill", skill_id, user_id
        )
        await session.close()

        session = _session()
        updated = await publish_review_service.approve(
            session, review.id, user_id, notes="ok"
        )
        await session.close()
        assert updated.status == "approved"

        async with _session() as s:
            skill = await skill_service.get_skill(s, skill_id)
            assert skill["is_published"] is True
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_reject_keeps_unpublished():
    skill_id = await _make_skill()
    user_id = await _real_user_id()
    try:
        session = _session()
        review = await publish_review_service.submit_review(
            session, "skill", skill_id, user_id
        )
        await session.close()

        session = _session()
        updated = await publish_review_service.reject(
            session, review.id, user_id, notes="no"
        )
        await session.close()
        assert updated.status == "rejected"

        async with _session() as s:
            skill = await skill_service.get_skill(s, skill_id)
            assert skill["is_published"] is False
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_withdraw_blocks_non_owner_and_non_pending():
    skill_id = await _make_skill()
    user_id = await _real_user_id()
    try:
        session = _session()
        review = await publish_review_service.submit_review(
            session, "skill", skill_id, user_id
        )
        await session.close()

        # 非创建者撤回 -> ValidationError
        session = _session()
        with pytest.raises(ValidationError):
            await publish_review_service.withdraw(session, review.id, user_id + 100000)
        await session.close()

        # 创建者撤回 -> withdrawn
        session = _session()
        updated = await publish_review_service.withdraw(session, review.id, user_id)
        await session.close()
        assert updated.status == "withdrawn"

        # 已 withdrawn 再撤回 -> ConflictError
        session = _session()
        with pytest.raises(ConflictError):
            await publish_review_service.withdraw(session, review.id, user_id)
        await session.close()
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_resolve_publish_gate_off_then_on():
    await _reset_gate(False)
    try:
        session = _session()
        eff, submit = await publish_review_service.resolve_publish(session, True)
        await session.close()
        assert eff is True and submit is False

        session = _session()
        eff, submit = await publish_review_service.resolve_publish(session, False)
        await session.close()
        assert eff is False and submit is False

        await _reset_gate(True)
        session = _session()
        eff, submit = await publish_review_service.resolve_publish(session, True)
        await session.close()
        assert eff is False and submit is True
    finally:
        await _reset_gate(False)


@pytest.mark.asyncio
async def test_update_publish_admin_bypasses_gate():
    """门控开启时：admin 拨 is_published 直接生效；普通 actor 转提审保持未发布。"""
    skill_id = await _make_skill()
    user_id = await _real_user_id()
    await _reset_gate(True)
    try:
        session = _session()
        await skill_service.update_skill(
            session, skill_id, actor_id=user_id, actor_is_admin=True, is_published=True
        )
        await session.close()
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            assert skill.is_published is True

        session = _session()
        await skill_service.update_skill(
            session, skill_id, actor_id=user_id, actor_is_admin=True, is_published=False
        )
        await session.close()
        session = _session()
        await skill_service.update_skill(
            session, skill_id, actor_id=user_id, is_published=True
        )
        await session.close()
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            assert skill.is_published is False
            review = await s.execute(
                select(PublishReview).where(
                    PublishReview.entity_type == "skill",
                    PublishReview.entity_id == skill_id,
                )
            )
            assert review.scalar_one().status == "pending"
    finally:
        await _reset_gate(False)
        await _cleanup_skill(skill_id)
