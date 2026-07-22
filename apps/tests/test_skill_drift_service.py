"""Skill 漂移检测单测（S9）。

走真实 DB（依赖 dev 中间件）。覆盖：
- _compute_drifted_files 纯函数各边界
- _bump_patch_version / _next_available_version
- check_single_drift：zip 跳过 / 检测到 drift / 拉取失败不误标 / 锁冲突
- resync_as_new_version：创建 inactive 新版本 + 版本号冲突自动 bump + 不激活
- create_skill / create_version 写路径补 source_type/source_url
"""

import os
import shutil
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete

from core.config import settings
from core.database import get_worker_session_factory
from exceptions import ConflictError, LockBusyError, ValidationError
from models.db import Skill, SkillVersion
from repositories import skill_repo, skill_version_repo
from services import skill_content_service, skill_drift_service, skill_service


def _session():
    return get_worker_session_factory()()


async def _make_skill(suffix: str | None = None, source_url: str | None = None):
    name = f"test_drift_{(suffix or uuid.uuid4().hex)[:8]}"
    session = _session()
    try:
        data = await skill_service.create_skill(
            session,
            name=name,
            version="1.0.0",
            zip_content=b"PK\x03\x04fake-skill-zip",
            zip_filename=f"{name}.zip",
            source_url=source_url,
        )
    finally:
        await session.close()
    return data["id"], data["skill_id"]


async def _cleanup(skill_ids: list[int]) -> None:
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


def _hash_entry(sha: str, size: int = 1) -> dict:
    return {"sha256": sha, "size": size}


# ─── 纯函数 ──────────────────────────────────────────────────────────────────


def test_compute_drifted_files_no_change():
    stored = {"a.md": _hash_entry("h1"), "b.md": _hash_entry("h2")}
    fresh = {"a.md": _hash_entry("h1"), "b.md": _hash_entry("h2")}
    assert skill_drift_service._compute_drifted_files(stored, fresh) == []


def test_compute_drifted_files_added_changed_deleted():
    stored = {"a.md": _hash_entry("h1"), "old.md": _hash_entry("h9")}
    fresh = {"a.md": _hash_entry("hX"), "new.md": _hash_entry("h2")}
    drifted = set(skill_drift_service._compute_drifted_files(stored, fresh))
    assert drifted == {"a.md", "new.md", "old.md"}


def test_compute_drifted_files_metadata_only_not_drift():
    """content_type/category 元数据差异不计入（仅 sha256 决定）。"""
    stored = {"a.md": {"sha256": "h1", "size": 1, "content_type": "text/markdown"}}
    fresh = {"a.md": {"sha256": "h1", "size": 1, "content_type": "text/plain"}}
    assert skill_drift_service._compute_drifted_files(stored, fresh) == []


def test_compute_drifted_files_empty_manifest():
    assert skill_drift_service._compute_drifted_files(
        {}, {"a.md": _hash_entry("h1")}
    ) == ["a.md"]
    assert skill_drift_service._compute_drifted_files(
        {"a.md": _hash_entry("h1")}, {}
    ) == ["a.md"]
    assert skill_drift_service._compute_drifted_files(None, None) == []


def test_bump_patch_version_normal():
    assert skill_drift_service._bump_patch_version("1.2.3") == "1.2.4"


def test_bump_patch_version_non_semver_raises():
    with pytest.raises(ValidationError):
        skill_drift_service._bump_patch_version("latest")
    with pytest.raises(ValidationError):
        skill_drift_service._bump_patch_version("1.0")
    with pytest.raises(ValidationError):
        skill_drift_service._bump_patch_version("1.2.x")


@pytest.mark.asyncio
async def test_next_available_version_conflict_then_free():
    skill_id, _ = await _make_skill(suffix="nv")
    try:
        session = _session()
        await skill_service.create_version(
            session, skill_id, version="1.0.1", zip_content=b"PK\x03\x04c1"
        )
        await session.close()
        # base 1.0.0 → 1.0.1 已占 → 跳到 1.0.2
        async with _session() as s:
            cand = await skill_drift_service._next_available_version(
                s, skill_id, "1.0.0"
            )
            assert cand == "1.0.2"
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_next_available_version_exhausted_raises():
    skill_id, _ = await _make_skill(suffix="ex")
    try:
        session = _session()
        for i in range(1, 7):
            await skill_service.create_version(
                session, skill_id, version=f"1.0.{i}", zip_content=b"PK\x03\x04c"
            )
        await session.close()
        async with _session() as s:
            with pytest.raises(ConflictError):
                await skill_drift_service._next_available_version(
                    s, skill_id, "1.0.0", max_attempts=2
                )
    finally:
        await _cleanup([skill_id])


# ─── 写路径补漏 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_skill_writes_source_type_url():
    skill_id, _ = await _make_skill(suffix="url", source_url="https://github.com/u/r")
    try:
        async with _session() as s:
            v = await skill_version_repo.find_active_for_skill(s, skill_id)
            assert v is not None
            assert v.source_type == "url"
            assert v.source_url == "https://github.com/u/r"
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_create_skill_zip_source_type_default():
    skill_id, _ = await _make_skill(suffix="zip")
    try:
        async with _session() as s:
            v = await skill_version_repo.find_active_for_skill(s, skill_id)
            assert v is not None
            assert v.source_type == "zip"
            assert v.source_url == ""
    finally:
        await _cleanup([skill_id])


# ─── check_single_drift ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_single_drift_zip_version_skipped():
    skill_id, _ = await _make_skill(suffix="skip")
    try:
        async with _session() as s:
            v = await skill_version_repo.find_active_for_skill(s, skill_id)
            with pytest.raises(ValidationError):
                await skill_drift_service.check_single_drift(s, v.id)
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_check_single_drift_detected_with_mock():
    """mock 拉取返回与存储不同的 zip → drift_detected=True，drifted_files 含变更文件。"""
    skill_id, _ = await _make_skill(suffix="det", source_url="https://github.com/u/r")
    try:
        async with _session() as s:
            v = await skill_version_repo.find_active_for_skill(s, skill_id)
            # 给存储值一个可对比的 file_hashes（原 fake-zip 可能无 SKILL.md，手动注入）
            await skill_version_repo.update_drift_status(
                s, v.id, drift_detected=False, drifted_files=[]
            )
            v.composite_hash = "stored-composite"
            v.file_hashes = {"SKILL.md": _hash_entry("stored-sha")}
            v.drift_check_error = ""
            await s.commit()
            await s.refresh(v)

        fake_zip = b"PK\x03\x04drifted-bytes"
        async with _session() as s:
            with patch.object(
                skill_drift_service,
                "_fetch_url_zip",
                new=AsyncMock(return_value=fake_zip),
            ):
                result = await skill_drift_service.check_single_drift(s, v.id)
            assert result["drift_detected"] is True
            assert len(result["drifted_files"]) > 0
            assert result["drift_check_error"] == ""
            assert result["last_drift_check_at"] is not None
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_check_single_drift_no_drift_with_mock():
    """mock 拉取返回完全相同的 hash → drift_detected=False。"""
    skill_id, _ = await _make_skill(
        suffix="nodrift", source_url="https://github.com/u/r"
    )
    try:
        async with _session() as s:
            v = await skill_version_repo.find_active_for_skill(s, skill_id)
            v.source_type = "url"
            v.source_url = "https://github.com/u/r"
            await s.commit()
            await s.refresh(v)

        # 计算 fake zip 的真实 hash 作为存储值
        fresh_composite, fresh_hashes = skill_content_service._compute_hashes(
            b"PK\x03\x04same-bytes"
        )
        async with _session() as s:
            v2 = await skill_version_repo.find_active_for_skill(s, skill_id)
            v2.composite_hash = fresh_composite
            v2.file_hashes = fresh_hashes
            await s.commit()
            await s.refresh(v2)

        async with _session() as s:
            with patch.object(
                skill_drift_service,
                "_fetch_url_zip",
                new=AsyncMock(return_value=b"PK\x03\x04same-bytes"),
            ):
                result = await skill_drift_service.check_single_drift(s, v2.id)
            assert result["drift_detected"] is False
            assert result["drifted_files"] == []
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_check_single_drift_fetch_failure_no_false_positive():
    """拉取失败 → 不标 drift，写 drift_check_error，抛 ValidationError。"""
    skill_id, _ = await _make_skill(suffix="fail", source_url="https://github.com/u/r")
    try:
        async with _session() as s:
            v = await skill_version_repo.find_active_for_skill(s, skill_id)
        async with _session() as s:
            with patch.object(
                skill_drift_service,
                "_fetch_url_zip",
                new=AsyncMock(side_effect=TimeoutError("connect timeout")),
            ):
                with pytest.raises(ValidationError):
                    await skill_drift_service.check_single_drift(s, v.id)
            # 失败写回：不标 drift + 记 error
            v3 = await skill_version_repo.find_by_id(s, v.id)
            assert v3.drift_detected is False
            assert "下载失败" in v3.drift_check_error
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_check_single_drift_lock_busy():
    """并发同 version_id：第二个抢锁抛 LockBusyError。"""
    skill_id, _ = await _make_skill(suffix="lock", source_url="https://github.com/u/r")
    try:
        async with _session() as s:
            v = await skill_version_repo.find_active_for_skill(s, skill_id)

        # 手动预占锁，模拟另一 worker 持有
        from core.redis_client import get_redis

        client = get_redis()
        await client.set(
            f"aihelms:lock:skill_drift:{v.id}", "other-token", nx=True, ex=60
        )
        try:
            async with _session() as s:
                with pytest.raises(LockBusyError):
                    await skill_drift_service.check_single_drift(s, v.id)
        finally:
            await client.delete(f"aihelms:lock:skill_drift:{v.id}")
    finally:
        await _cleanup([skill_id])


# ─── resync ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resync_creates_inactive_version():
    """resync 把源内容作为新版本入库（inactive + 未审查），不激活旧 active。"""
    skill_id, _ = await _make_skill(suffix="rs", source_url="https://github.com/u/r")
    try:
        async with _session() as s:
            v = await skill_version_repo.find_active_for_skill(s, skill_id)
            old_active_id = v.id

        fake_zip = b"PK\x03\x04resynced-content"
        async with _session() as s:
            with patch.object(
                skill_drift_service,
                "_fetch_url_zip",
                new=AsyncMock(return_value=fake_zip),
            ):
                new_v = await skill_drift_service.resync_as_new_version(
                    s, old_active_id, created_by=None
                )
            assert new_v["is_active"] is False
            assert new_v["lifecycle_status"] == "draft"
            assert new_v["security_status"] == "not_scanned"
            assert new_v["source_type"] == "url"
            assert new_v["source_url"] == "https://github.com/u/r"

        # 旧 active 仍是 active
        async with _session() as s:
            active = await skill_version_repo.find_active_for_skill(s, skill_id)
            assert active is not None
            assert active.id == old_active_id
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_resync_bumps_version_on_conflict():
    """显式目标版本号冲突 → ConflictError。"""
    skill_id, _ = await _make_skill(
        suffix="rsclash", source_url="https://github.com/u/r"
    )
    try:
        async with _session() as s:
            v = await skill_version_repo.find_active_for_skill(s, skill_id)

        async with _session() as s:
            with patch.object(
                skill_drift_service,
                "_fetch_url_zip",
                new=AsyncMock(return_value=b"PK\x03\x04c"),
            ):
                with pytest.raises(ConflictError):
                    await skill_drift_service.resync_as_new_version(
                        s, v.id, new_version="1.0.0", created_by=None
                    )
    finally:
        await _cleanup([skill_id])
