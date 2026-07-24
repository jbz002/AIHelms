"""S3 · Skill 生命周期状态机精细化测试。

纯单元（assert_transition 合法性）+ 真实 DB（依赖 dev 中间件）：
- migration 兼容映射：create_skill 种 v1 为 published
- Yank 命中 current_version_id 重算到次新 published
"""

import io
import os
import shutil
import uuid
import zipfile

import pytest
from sqlalchemy import delete

from core.config import settings
from core.database import get_worker_session_factory
from exceptions import ValidationError
from models.db import Skill, SkillVersion
from repositories import skill_repo, skill_version_repo
from services import skill_service
from services.skill_lifecycle_service import (
    DEPRECATED,
    DRAFT,
    PENDING_REVIEW,
    PUBLISHED,
    REJECTED,
    SCANNING,
    YANKED,
    assert_transition,
)


def _session():
    return get_worker_session_factory()()


def _valid_zip(name: str = "my-skill") -> bytes:
    """构造通过 S5 包校验 + S1 协议校验的最小 zip（含 SKILL.md）。"""
    skill_md = (
        f"---\nname: {name}\ndescription: A test skill.\n---\n\n# {name}\n\nBody."
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", skill_md)
    return buf.getvalue()


# ─── 纯单元：状态流转合法性 ─────────────────────────────────────────────────


def test_transition_draft_to_published_legal():
    assert_transition(DRAFT, PUBLISHED)
    assert_transition(DRAFT, SCANNING)
    assert_transition(DRAFT, PENDING_REVIEW)


def test_transition_pending_review_to_published_or_rejected():
    assert_transition(PENDING_REVIEW, PUBLISHED)
    assert_transition(PENDING_REVIEW, REJECTED)
    assert_transition(PENDING_REVIEW, DRAFT)  # 撤回回 draft


def test_transition_published_to_yanked_or_deprecated():
    assert_transition(PUBLISHED, YANKED)
    assert_transition(PUBLISHED, DEPRECATED)


def test_transition_terminal_states_blocked():
    for terminal in (YANKED, REJECTED, DEPRECATED):
        with pytest.raises(ValidationError):
            assert_transition(terminal, PUBLISHED)
    # 非法回流
    with pytest.raises(ValidationError):
        assert_transition(PUBLISHED, DRAFT)
    with pytest.raises(ValidationError):
        assert_transition(DEPRECATED, PUBLISHED)


# ─── DB 辅助 ─────────────────────────────────────────────────────────────────


async def _make_skill(suffix: str | None = None) -> int:
    name = f"test_s3_{(suffix or uuid.uuid4().hex)[:8]}"
    session = _session()
    try:
        data = await skill_service.create_skill(
            session,
            name=name,
            version="1.0.0",
            zip_content=_valid_zip(name),
            zip_filename=f"{name}.zip",
        )
    finally:
        await session.close()
    return int(data["id"])


async def _cleanup(skill_ids: list[int]) -> None:
    async with _session() as s:
        await s.execute(
            delete(SkillVersion).where(SkillVersion.skill_id.in_(skill_ids))
        )
        await s.execute(delete(Skill).where(Skill.id.in_(skill_ids)))
        await s.commit()
    for sid in skill_ids:
        async with _session() as s:
            skill = await skill_repo.find_by_id(s, sid)
            if skill:
                version_dir = os.path.join(settings.skills_storage_dir, skill.skill_id)
                if os.path.isdir(version_dir):
                    shutil.rmtree(version_dir, ignore_errors=True)


async def _stage_activatable_version(skill_id: int, version: str) -> int:
    """创建新版本并直接置为可通过激活门控（security completed + protocol_valid）。"""
    session = _session()
    try:
        data = await skill_service.create_version(
            session, skill_id, version=version, created_by=None
        )
    finally:
        await session.close()
    vid = int(data["id"])
    async with _session() as s:
        v = await skill_version_repo.find_by_id(s, vid)
        assert v is not None
        v.security_status = "completed"
        v.security_decision = "passed"
        v.protocol_valid = True
        await s.commit()
    return vid


# ─── DB 集成 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_skill_seeds_v1_published():
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            versions = await skill_version_repo.list_versions(s, skill_id)
            assert len(versions) == 1
            assert versions[0].lifecycle_status == PUBLISHED
            assert versions[0].is_active is True
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_yank_recomputes_pointer_to_previous_published():
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            versions = await skill_version_repo.list_versions(s, skill_id)
            v1 = versions[0]
        v2 = await _stage_activatable_version(skill_id, "2.0.0")

        session = _session()
        try:
            await skill_service.activate_version(session, skill_id, v2)
        finally:
            await session.close()

        async with _session() as s:
            skill = await skill_repo.find_by_id(s, skill_id)
            assert skill is not None
            assert skill.current_version_id == v2

        # 撤回 v2 → 重算到 v1（仍为 published，恢复 is_active）
        session = _session()
        try:
            await skill_service.yank_version(session, skill_id, v2)
        finally:
            await session.close()

        async with _session() as s:
            skill = await skill_repo.find_by_id(s, skill_id)
            v1_refreshed = await skill_version_repo.find_by_id(s, v1.id)
            v2_refreshed = await skill_version_repo.find_by_id(s, v2)
            assert skill is not None
            assert skill.current_version_id == v1.id
            assert v1_refreshed.lifecycle_status == PUBLISHED
            assert v1_refreshed.is_active is True
            assert v2_refreshed.lifecycle_status == YANKED
            assert v2_refreshed.is_active is False
    finally:
        await _cleanup([skill_id])
