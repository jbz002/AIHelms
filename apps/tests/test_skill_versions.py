"""Skill 版本管理集成测试。

走真实 DB（依赖 dev 中间件运行），覆盖：
- create_skill 自动种 v1 active 版本
- create_version 起步为 inactive + 未审查，并写入 per-version zip
- 激活硬门控：未通过安全审查的新版本不可激活
- 通过安全审查（passed）的新版本可激活，并翻转 active + 主表快照
- 单 active 部分唯一索引
- deprecate 守卫 + 默认列表过滤
"""

import os
import shutil
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from core.config import settings
from core.database import get_worker_session_factory
from exceptions import ValidationError
from models.db import Skill, SkillVersion
from repositories import skill_repo, skill_version_repo
from services import skill_service


def _session():
    """测试用 NullPool 的 worker session factory，避免 asyncpg QueuePool 连接绑定到
    创建时的事件循环而在 pytest 新事件循环中复用失败。"""
    return get_worker_session_factory()()


async def _make_skill(suffix: str | None = None) -> tuple[int, str]:
    name = f"test_sv_{(suffix or uuid.uuid4().hex)[:8]}"
    session = _session()
    try:
        data = await skill_service.create_skill(
            session,
            name=name,
            version="1.0.0",
            zip_content=b"PK\x03\x04fake-skill-zip",
            zip_filename=f"{name}.zip",
        )
    finally:
        await session.close()
    return data["id"], data["skill_id"]


async def _cleanup(skill_ids: list[int]) -> None:
    """直接清理 DB 行 + zip 文件，避免触发 ai_key_service 副作用。"""
    async with _session() as s:
        for sid in skill_ids:
            versions = await skill_version_repo.list_versions(s, sid)
            skill = await skill_repo.find_by_id(s, sid)
            paths = {v.zip_path for v in versions if v.zip_path}
            if skill and skill.zip_path:
                paths.add(skill.zip_path)
            for path in paths:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            if skill:
                version_dir = os.path.join(settings.skills_storage_dir, skill.skill_id)
                if os.path.isdir(version_dir):
                    shutil.rmtree(version_dir, ignore_errors=True)
        await s.execute(
            delete(SkillVersion).where(SkillVersion.skill_id.in_(skill_ids))
        )
        await s.execute(delete(Skill).where(Skill.id.in_(skill_ids)))
        await s.commit()


@pytest.mark.asyncio
async def test_create_skill_seeds_v1_active():
    skill_id, _ = await _make_skill()
    try:
        async with _session() as s:
            versions = await skill_version_repo.list_versions(s, skill_id)
            assert len(versions) == 1
            assert versions[0].version == "1.0.0"
            assert versions[0].is_active is True
            assert versions[0].lifecycle_status == "active"
            skill = await s.get(Skill, skill_id)
            assert skill.current_version_id == versions[0].id
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_create_version_starts_inactive_and_writes_per_version_zip():
    skill_id, skill_uuid = await _make_skill()
    try:
        session = _session()
        data = await skill_service.create_version(
            session,
            skill_id,
            version="2.0.0",
            zip_content=b"PK\x03\x04v2-content",
            zip_filename="v2.zip",
            change_log="canary",
        )
        await session.close()
        assert data["is_active"] is False
        assert data["lifecycle_status"] == "inactive"
        assert data["security_status"] == "not_scanned"
        # per-version zip 写入 {skills_storage_dir}/{skill_uuid}/{version_id}.zip
        version_dir = os.path.join(settings.skills_storage_dir, skill_uuid)
        assert os.path.isdir(version_dir)
        assert os.path.exists(os.path.join(version_dir, f"{data['id']}.zip"))
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_activate_blocks_unscanned_version():
    """硬门控：未通过安全审查的新版本不可激活。"""
    skill_id, _ = await _make_skill()
    try:
        session = _session()
        await skill_service.create_version(
            session,
            skill_id,
            version="2.0.0",
            zip_content=b"PK\x03\x04v2",
            zip_filename="v2.zip",
        )
        v2 = await skill_version_repo.find_by_skill_and_version(
            session, skill_id, "2.0.0"
        )
        v2_id = v2.id
        await session.close()

        session = _session()
        with pytest.raises(ValidationError):
            await skill_service.activate_version(session, skill_id, v2_id)
        await session.close()

        # active 仍是 v1
        async with _session() as s:
            active = await skill_version_repo.find_active_for_skill(s, skill_id)
            assert active.version == "1.0.0"
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_activate_allows_passed_version():
    """通过安全审查（passed）的新版本可激活，并翻转 active + 主表快照。"""
    skill_id, _ = await _make_skill()
    try:
        session = _session()
        await skill_service.create_version(
            session,
            skill_id,
            version="2.0.0",
            zip_content=b"PK\x03\x04v2",
            zip_filename="v2.zip",
        )
        v2 = await skill_version_repo.find_by_skill_and_version(
            session, skill_id, "2.0.0"
        )
        v2_id = v2.id
        # 模拟版本绑定安全审查通过
        await skill_version_repo.update_security_status(
            session,
            v2_id,
            status="completed",
            decision="passed",
            severity="none",
            risk_score=0,
            audit_id=None,
        )
        # 模拟协议校验通过（S1 激活门控）
        v2.protocol_valid = True
        await session.commit()
        await session.close()

        session = _session()
        data = await skill_service.activate_version(session, skill_id, v2_id)
        await session.close()

        assert data["active_version"]["version"] == "2.0.0"
        assert data["version"] == "2.0.0"  # 主表 version 已切到 v2

        async with _session() as s:
            versions = {
                v.version: v
                for v in await skill_version_repo.list_versions(s, skill_id)
            }
            assert versions["2.0.0"].is_active is True
            assert versions["1.0.0"].is_active is False
            skill = await s.get(Skill, skill_id)
            assert skill.current_version_id == versions["2.0.0"].id
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_activate_blocks_invalid_protocol_version():
    """协议门控（S1）：protocol_valid=False 的新版本即使安全审查通过也不可激活。"""
    skill_id, _ = await _make_skill()
    try:
        session = _session()
        await skill_service.create_version(
            session,
            skill_id,
            version="2.0.0",
            zip_content=b"PK\x03\x04v2",
            zip_filename="v2.zip",
        )
        v2 = await skill_version_repo.find_by_skill_and_version(
            session, skill_id, "2.0.0"
        )
        v2_id = v2.id
        # 安全审查通过但协议校验未通过（fake zip 无 SKILL.md）
        await skill_version_repo.update_security_status(
            session,
            v2_id,
            status="completed",
            decision="passed",
            severity="none",
            risk_score=0,
            audit_id=None,
        )
        assert v2.protocol_valid is False
        await session.commit()
        await session.close()

        session = _session()
        with pytest.raises(ValidationError):
            await skill_service.activate_version(session, skill_id, v2_id)
        await session.close()

        async with _session() as s:
            active = await skill_version_repo.find_active_for_skill(s, skill_id)
            assert active.version == "1.0.0"
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_single_active_invariant_enforced_by_index():
    """部分唯一索引保证每逻辑 Skill 至多 1 个 active（DB 层兜底）。"""
    skill_id, _ = await _make_skill()
    try:
        async with _session() as s:
            v2 = SkillVersion(
                skill_id=skill_id,
                version="2.0.0",
                is_active=True,
                lifecycle_status="active",
            )
            s.add(v2)
            with pytest.raises(IntegrityError):
                await s.flush()
            await s.rollback()
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_deprecate_guard_and_list_filter():
    skill_id, _ = await _make_skill()
    try:
        session = _session()
        await skill_service.create_version(
            session,
            skill_id,
            version="2.0.0",
            zip_content=b"PK\x03\x04v2",
            zip_filename="v2.zip",
        )
        v2 = await skill_version_repo.find_by_skill_and_version(
            session, skill_id, "2.0.0"
        )
        v1 = await skill_version_repo.find_active_for_skill(session, skill_id)
        # 弃用 active 版本应被拒绝
        with pytest.raises(ValidationError):
            await skill_service.deprecate_version(session, skill_id, v1.id)
        # 弃用 inactive 版本成功
        await skill_service.deprecate_version(session, skill_id, v2.id)
        await session.close()

        # admin 版本列表默认展示全部（含弃用）；include_deprecated=False 才过滤
        session2 = _session()
        default_list = await skill_service.list_versions(session2, skill_id)
        filtered = await skill_service.list_versions(
            session2, skill_id, include_deprecated=False
        )
        await session2.close()
        assert len(default_list) == 2
        assert any(v["lifecycle_status"] == "deprecated" for v in default_list)
        assert len(filtered) == 1
        assert filtered[0]["lifecycle_status"] == "active"
    finally:
        await _cleanup([skill_id])
