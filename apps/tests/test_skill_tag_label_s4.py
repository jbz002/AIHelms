"""S4 · Skill Tag + Label 双层体系测试（依赖 dev 中间件真实 DB）。

- SkillTag 创建/移动；latest 系统保留只读；create/yank 自动刷新 latest 指针。
- 治理 Label 授予/撤销/幂等冲突；label_definitions CRUD；权限点已注册。
"""

import io
import uuid
import zipfile

import pytest
from sqlalchemy import delete, select

from core.database import get_worker_session_factory
from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import (
    LabelDefinition,
    Permission,
    Skill,
    SkillLabel,
    SkillTag,
    SkillVersion,
)
from repositories import skill_tag_repo, skill_version_repo
from services import skill_label_service, skill_service, skill_tag_service


def _session():
    return get_worker_session_factory()()


def _valid_zip(name: str = "my-skill") -> bytes:
    skill_md = (
        f"---\nname: {name}\ndescription: A test skill.\n---\n\n# {name}\n\nBody."
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", skill_md)
    return buf.getvalue()


async def _make_skill(suffix: str | None = None) -> int:
    name = f"test_s4_{(suffix or uuid.uuid4().hex)[:8]}"
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


async def _stage_activatable_version(skill_id: int, version: str) -> int:
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


async def _cleanup(skill_ids: list[int], def_names: list[str] | None = None) -> None:
    async with _session() as s:
        await s.execute(delete(SkillTag).where(SkillTag.skill_id.in_(skill_ids)))
        await s.execute(delete(SkillLabel).where(SkillLabel.skill_id.in_(skill_ids)))
        await s.execute(
            delete(SkillVersion).where(SkillVersion.skill_id.in_(skill_ids))
        )
        await s.execute(delete(Skill).where(Skill.id.in_(skill_ids)))
        if def_names:
            await s.execute(
                delete(LabelDefinition).where(LabelDefinition.name.in_(def_names))
            )
        await s.commit()


# ─── SkillTag ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_tag_refresh_on_create_seeds_latest():
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            versions = await skill_version_repo.list_versions(s, skill_id)
            v1 = versions[0]
            latest = await skill_tag_repo.find_system_latest(s, skill_id)
            assert latest is not None
            assert latest.is_system is True
            assert latest.version_id == v1.id
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_skill_tag_latest_is_system_readonly():
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            versions = await skill_version_repo.list_versions(s, skill_id)
            v1 = versions[0]
        session = _session()
        try:
            with pytest.raises(ValidationError):
                await skill_tag_service.create_or_move_tag(
                    session, skill_id, "latest", v1.id
                )
            # 系统标签不可删除
            with pytest.raises(ValidationError):
                await skill_tag_service.delete_tag(session, skill_id, "latest")
        finally:
            await session.close()
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_skill_tag_create_or_move_succeeds():
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            versions = await skill_version_repo.list_versions(s, skill_id)
            v1 = versions[0]
        v2 = await _stage_activatable_version(skill_id, "2.0.0")

        session = _session()
        try:
            await skill_tag_service.create_or_move_tag(session, skill_id, "beta", v1.id)
        finally:
            await session.close()

        async with _session() as s:
            tag = await skill_tag_repo.find_by_skill_and_name(s, skill_id, "beta")
            assert tag is not None
            assert tag.version_id == v1.id
            assert tag.is_system is False

        # 移动 beta → v2
        session = _session()
        try:
            await skill_tag_service.create_or_move_tag(session, skill_id, "beta", v2)
        finally:
            await session.close()
        async with _session() as s:
            tag = await skill_tag_repo.find_by_skill_and_name(s, skill_id, "beta")
            assert tag is not None
            assert tag.version_id == v2
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_skill_tag_refresh_on_yank_recomputes_latest():
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
            latest = await skill_tag_repo.find_system_latest(s, skill_id)
            assert latest is not None
            assert latest.version_id == v2

        # 撤回 v2 → latest 重算到 v1
        session = _session()
        try:
            await skill_service.yank_version(session, skill_id, v2)
        finally:
            await session.close()
        async with _session() as s:
            latest = await skill_tag_repo.find_system_latest(s, skill_id)
            assert latest is not None
            assert latest.version_id == v1.id
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_skill_tag_delete_user_tag():
    skill_id = await _make_skill()
    try:
        async with _session() as s:
            versions = await skill_version_repo.list_versions(s, skill_id)
            v1 = versions[0]
        session = _session()
        try:
            await skill_tag_service.create_or_move_tag(
                session, skill_id, "stable", v1.id
            )
            await skill_tag_service.delete_tag(session, skill_id, "stable")
        finally:
            await session.close()
        async with _session() as s:
            tag = await skill_tag_repo.find_by_skill_and_name(s, skill_id, "stable")
            assert tag is None
    finally:
        await _cleanup([skill_id])


# ─── 治理 Label ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_label_grant_and_revoke():
    skill_id = await _make_skill()
    try:
        session = _session()
        try:
            await skill_label_service.grant_label(
                session, skill_id, "recommended", granted_by=None, note="seed"
            )
        finally:
            await session.close()
        async with _session() as s:
            labels = await skill_label_service.list_labels(s, skill_id)
            assert len(labels) == 1
            assert labels[0]["name"] == "recommended"

        session = _session()
        try:
            await skill_label_service.revoke_label(session, skill_id, "recommended")
        finally:
            await session.close()
        async with _session() as s:
            labels = await skill_label_service.list_labels(s, skill_id)
            assert labels == []
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_skill_label_grant_idempotent_conflict():
    skill_id = await _make_skill()
    try:
        session = _session()
        try:
            await skill_label_service.grant_label(
                session, skill_id, "official", granted_by=None
            )
        finally:
            await session.close()
        session = _session()
        try:
            with pytest.raises(ConflictError):
                await skill_label_service.grant_label(
                    session, skill_id, "official", granted_by=None
                )
        finally:
            await session.close()
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_skill_label_revoke_missing_not_found():
    skill_id = await _make_skill()
    try:
        session = _session()
        try:
            with pytest.raises(NotFoundError):
                await skill_label_service.revoke_label(session, skill_id, "verified")
        finally:
            await session.close()
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_label_definition_crud():
    try:
        async with _session() as s:
            seeded = await skill_label_service.list_definitions(s, active_only=False)
            names = {d["name"] for d in seeded}
            assert {"recommended", "official", "verified"} <= names

        session = _session()
        try:
            created = await skill_label_service.create_definition(
                session,
                name="experimental",
                display_name_key="label.experimental.title",
                color="slate",
                sort_order=40,
            )
        finally:
            await session.close()
        assert created["name"] == "experimental"

        session = _session()
        try:
            updated = await skill_label_service.update_definition(
                session, created["id"], color="amber", sort_order=99
            )
        finally:
            await session.close()
        assert updated["color"] == "amber"
        assert updated["sort_order"] == 99

        session = _session()
        try:
            await skill_label_service.deactivate_definition(session, created["id"])
        finally:
            await session.close()
        async with _session() as s:
            active = await skill_label_service.list_definitions(s, active_only=True)
            assert "experimental" not in {d["name"] for d in active}
    finally:
        await _cleanup([], def_names=["experimental"])


@pytest.mark.asyncio
async def test_skill_label_manage_permission_registered():
    """权限点 skill:label:manage 已 seed（admin-only by is_admin bypass）。"""
    async with _session() as s:
        result = await s.execute(
            select(Permission).where(Permission.code == "skill:label:manage")
        )
        perm = result.scalar_one_or_none()
        assert perm is not None
        assert perm.resource == "skill"
