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


def test_transition_yanked_restorable():
    # yanked 不再终态，可恢复到 published（不自动激活）
    assert_transition(YANKED, PUBLISHED)


def test_transition_terminal_states_blocked():
    for terminal in (REJECTED, DEPRECATED):
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
async def test_restore_single_version_reactivates():
    """单版本撤回 → 恢复：current 为 None，restore 重新激活回撤回前状态。"""
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            v1 = (await skill_version_repo.list_versions(s, skill_id))[0]
            # create_skill 现状种 draft；直接置 published+active 以独立验 restore 链路
            v1.lifecycle_status = PUBLISHED
            v1.is_active = True
            skill = await skill_repo.find_by_id(s, skill_id)
            assert skill is not None
            skill.current_version_id = v1.id
            await s.commit()

        # 撤回 v1 → yanked，无次新 published，current_version_id 置空
        session = _session()
        try:
            await skill_service.yank_version(session, skill_id, v1.id)
        finally:
            await session.close()
        async with _session() as s:
            v = await skill_version_repo.find_by_id(s, v1.id)
            skill = await skill_repo.find_by_id(s, skill_id)
            assert v.lifecycle_status == YANKED
            assert v.is_active is False
            assert skill is not None
            assert skill.current_version_id is None

        # 恢复 v1（单版本，current 为 None）→ 重新激活，回到撤回前
        session = _session()
        try:
            await skill_service.restore_version(session, skill_id, v1.id)
        finally:
            await session.close()
        async with _session() as s:
            v = await skill_version_repo.find_by_id(s, v1.id)
            skill = await skill_repo.find_by_id(s, skill_id)
            assert v.lifecycle_status == PUBLISHED
            assert v.is_active is True
            assert skill is not None
            assert skill.current_version_id == v1.id

        # 非 yanked 状态恢复被拦
        session = _session()
        try:
            with pytest.raises(ValidationError):
                await skill_service.restore_version(session, skill_id, v1.id)
        finally:
            await session.close()
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_restore_with_other_active_stays_candidate():
    """多版本：v2 已 active 时恢复 v1 → published+inactive 候选，不抢夺 current。"""
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            v1 = (await skill_version_repo.list_versions(s, skill_id))[0]
            v1.lifecycle_status = PUBLISHED
            v1.is_active = True
            skill = await skill_repo.find_by_id(s, skill_id)
            assert skill is not None
            skill.current_version_id = v1.id
            await s.commit()
        v2 = await _stage_activatable_version(skill_id, "2.0.0")
        # 激活 v2 → v1 降为 published+inactive
        session = _session()
        try:
            await skill_service.activate_version(session, skill_id, v2)
        finally:
            await session.close()
        # 撤回 v1（非 current，仅翻 lifecycle）
        session = _session()
        try:
            await skill_service.yank_version(session, skill_id, v1.id)
        finally:
            await session.close()
        # 恢复 v1（v2 仍 active）→ published+inactive 候选，不抢夺
        session = _session()
        try:
            await skill_service.restore_version(session, skill_id, v1.id)
        finally:
            await session.close()
        async with _session() as s:
            v1r = await skill_version_repo.find_by_id(s, v1.id)
            v2r = await skill_version_repo.find_by_id(s, v2)
            skill = await skill_repo.find_by_id(s, skill_id)
            assert v1r.lifecycle_status == PUBLISHED
            assert v1r.is_active is False
            assert v2r.is_active is True
            assert skill is not None
            assert skill.current_version_id == v2
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_published_inactive_can_reactivate():
    """published+inactive 历史版本可重新激活（多版本回切）。"""
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            v1 = (await skill_version_repo.list_versions(s, skill_id))[0]
            v1.lifecycle_status = PUBLISHED
            v1.is_active = True
            v1.security_status = "completed"
            v1.security_decision = "passed"
            v1.protocol_valid = True
            skill = await skill_repo.find_by_id(s, skill_id)
            assert skill is not None
            skill.current_version_id = v1.id
            await s.commit()
        v2 = await _stage_activatable_version(skill_id, "2.0.0")
        # 激活 v2 → v1 降 published+inactive
        session = _session()
        try:
            await skill_service.activate_version(session, skill_id, v2)
        finally:
            await session.close()
        async with _session() as s:
            v1r = await skill_version_repo.find_by_id(s, v1.id)
            assert v1r.lifecycle_status == PUBLISHED
            assert v1r.is_active is False
        # 回切 v1（published+inactive 可重新激活）
        session = _session()
        try:
            await skill_service.activate_version(session, skill_id, v1.id)
        finally:
            await session.close()
        async with _session() as s:
            v1r = await skill_version_repo.find_by_id(s, v1.id)
            v2r = await skill_version_repo.find_by_id(s, v2)
            skill = await skill_repo.find_by_id(s, skill_id)
            assert v1r.is_active is True
            assert v2r.is_active is False
            assert skill is not None
            assert skill.current_version_id == v1.id
    finally:
        await _cleanup([skill_id])
