"""S6 一致性保障与审计强化集成测试。

走真实 DB + Redis（依赖 dev 中间件运行），覆盖：
- 幂等 repo：upsert 命中既有 key 不覆盖；save_response + find_by_key 回放
- 乐观锁：skill_version / resource_application / rating 的 lock_version CAS
- 分布式锁：同 key 第二次抢锁抛 LockBusyError
- 存储删除补偿：inc_retry 达上限标 failed；_purge_files_after_commit 删失败落补偿表
- 审计：AdminAuditLog 的 request_id / detail 字段持久化
"""

import shutil
import uuid
from datetime import datetime

import pytest
from sqlalchemy import delete, select

from core.config import settings
from core.database import get_worker_session_factory
from core.distributed_lock import redis_lock
from exceptions import ConflictError, LockBusyError
from models.db import (
    AdminAuditLog,
    EntityRating,
    EntityRatingStats,
    IdempotencyRecord,
    ResourceApplication,
    Skill,
    SkillVersion,
    StorageDeletionCompensation,
    User,
)
from repositories import (
    idempotency_repo,
    rating_repo,
    resource_application_repo,
    skill_version_repo,
    storage_deletion_compensation_repo,
)
from services import skill_service


def _session():
    return get_worker_session_factory()()


async def _real_user_id() -> int:
    async with _session() as s:
        result = await s.execute(select(User.id).limit(1))
        row = result.scalar_one_or_none()
        assert row is not None, "测试需至少一个真实用户"
        return int(row)


async def _make_skill() -> int:
    name = f"test_s6_{uuid.uuid4().hex[:8]}"
    session = _session()
    try:
        data = await skill_service.create_skill(
            session,
            name=name,
            version="1.0.0",
            zip_content=b"PK\x03\x04fake-s6",
            zip_filename=f"{name}.zip",
        )
    finally:
        await session.close()
    return data["id"]


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
async def test_idempotency_repo_upsert_and_replay():
    key = f"idem-{uuid.uuid4().hex}"
    try:
        async with _session() as s:
            rec, created = await idempotency_repo.upsert_record(
                s, key=key, entity_type="write", request_hash="hash-1", ttl_hours=24
            )
            assert created

        # 同 key 不同 hash：既有记录不被覆盖
        async with _session() as s:
            rec2, created2 = await idempotency_repo.upsert_record(
                s, key=key, entity_type="write", request_hash="hash-2", ttl_hours=24
            )
            assert not created2
            assert rec2.request_hash == "hash-1"
            assert rec2.id == rec.id

        async with _session() as s:
            await idempotency_repo.save_response(
                s, rec.id, 200, {"code": 200, "data": {"id": 1}}
            )

        async with _session() as s:
            found = await idempotency_repo.find_by_key(s, key)
            assert found is not None
            assert found.response_code == 200
            assert found.response_body["data"]["id"] == 1
    finally:
        async with _session() as s:
            await s.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.key == key)
            )
            await s.commit()


@pytest.mark.asyncio
async def test_optimistic_lock_skill_version_conflict():
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            versions = await skill_version_repo.list_versions(s, skill_id)
            v = versions[0]
            base = v.lock_version
            # 期望值过时 → ConflictError
            with pytest.raises(ConflictError):
                await skill_version_repo.set_active_with_lock(s, v.id, base + 999)

        # 正确期望值 → 激活成功，lock_version +1
        async with _session() as s:
            await skill_version_repo.set_active_with_lock(s, v.id, base)
            await s.commit()

        async with _session() as s:
            v2 = await skill_version_repo.find_by_id(s, v.id)
            assert v2 is not None
            assert v2.lock_version == base + 1
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_optimistic_lock_resource_application_conflict():
    async with _session() as s:
        app = ResourceApplication(
            resource_type="skill", resource_id=999999, status="pending"
        )
        s.add(app)
        await s.flush()
        await s.refresh(app)
        app_id = app.id
        await s.commit()

    try:
        async with _session() as s:
            with pytest.raises(ConflictError):
                await resource_application_repo.update_status_with_lock(
                    s,
                    app_id,
                    999,
                    status="approved",
                    reviewed_by=None,
                    reviewed_at=datetime.utcnow(),
                    review_notes="",
                    approval_config={},
                )

        async with _session() as s:
            await resource_application_repo.update_status_with_lock(
                s,
                app_id,
                0,
                status="approved",
                reviewed_by=None,
                reviewed_at=datetime.utcnow(),
                review_notes="ok",
                approval_config={"valid_days": 30},
            )
            await s.commit()

        async with _session() as s:
            a2 = await resource_application_repo.find_by_id(s, app_id)
            assert a2 is not None
            assert a2.status == "approved"
            assert a2.lock_version == 1
    finally:
        async with _session() as s:
            await s.execute(
                delete(ResourceApplication).where(ResourceApplication.id == app_id)
            )
            await s.commit()


@pytest.mark.asyncio
async def test_optimistic_lock_rating_upsert_increments():
    skill_id = await _make_skill()
    user_id = await _real_user_id()
    try:
        async with _session() as s:
            r = await rating_repo.upsert_rating(s, "skill", skill_id, user_id, 4)
            assert r.lock_version == 0
            await s.commit()

        # existing 分支：带锁 update，lock_version 递增
        async with _session() as s:
            r = await rating_repo.upsert_rating(s, "skill", skill_id, user_id, 5)
            assert r.lock_version == 1
            await s.commit()
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_distributed_lock_mutual_exclusion():
    key = f"aihelms:test:lock:{uuid.uuid4().hex}"
    async with redis_lock(key):
        with pytest.raises(LockBusyError):
            async with redis_lock(key):
                pass


@pytest.mark.asyncio
async def test_storage_compensation_inc_retry_threshold():
    async with _session() as s:
        comp = await storage_deletion_compensation_repo.create(
            s, entity_type="skill", storage_path=f"/tmp/s6_test_{uuid.uuid4().hex}"
        )
        await s.commit()
        comp_id = comp.id

    max_retries = settings.storage_compensation_max_retries
    try:
        # 上限 - 1 次仍 pending
        for _ in range(max_retries - 1):
            async with _session() as s:
                status = await storage_deletion_compensation_repo.inc_retry(
                    s, comp_id, "err", max_retries
                )
                await s.commit()
        assert status == "pending"

        # 达上限 → failed
        async with _session() as s:
            status = await storage_deletion_compensation_repo.inc_retry(
                s, comp_id, "err", max_retries
            )
            await s.commit()
        assert status == "failed"

        async with _session() as s:
            c2 = await s.get(StorageDeletionCompensation, comp_id)
            assert c2.status == "failed"
            assert c2.retries == max_retries
    finally:
        async with _session() as s:
            await s.execute(
                delete(StorageDeletionCompensation).where(
                    StorageDeletionCompensation.id == comp_id
                )
            )
            await s.commit()


@pytest.mark.asyncio
async def test_purge_files_after_commit_records_compensation(tmp_path):
    # 目录：os.remove 抛 OSError（Windows PermissionError / Linux IsADirectoryError）
    blocked_dir = tmp_path / "blocked"
    blocked_dir.mkdir()
    path = str(blocked_dir)

    await skill_service._purge_files_after_commit("skill", 888888, {path})

    try:
        async with _session() as s:
            pending = await storage_deletion_compensation_repo.list_pending(s)
            matched = [c for c in pending if c.storage_path == path]
            assert matched, "删失败应落补偿记录"
            comp_id = matched[0].id
    finally:
        async with _session() as s:
            await s.execute(
                delete(StorageDeletionCompensation).where(
                    StorageDeletionCompensation.id == comp_id
                )
            )
            await s.commit()
        shutil.rmtree(blocked_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_audit_log_request_id_detail_persisted():
    request_id = f"rid-{uuid.uuid4().hex}"
    log = AdminAuditLog(
        user_id=0,
        username="s6-tester",
        method="POST",
        path="/api/v1/s6-test",
        action="S6 测试动作",
        status_code=200,
        request_id=request_id,
        detail={"affected_entity_ids": [1, 2, 3], "scope": "batch"},
    )
    async with _session() as s:
        s.add(log)
        await s.flush()
        await s.refresh(log)
        await s.commit()
        log_id = log.id

    try:
        async with _session() as s:
            loaded = await s.get(AdminAuditLog, log_id)
            assert loaded is not None
            assert loaded.request_id == request_id
            assert loaded.detail["affected_entity_ids"] == [1, 2, 3]
            assert loaded.detail["scope"] == "batch"
    finally:
        async with _session() as s:
            await s.execute(delete(AdminAuditLog).where(AdminAuditLog.id == log_id))
            await s.commit()
