"""贡献者 Skill router 所有权与草稿语义测试（走真实 DB，依赖 dev 中间件运行）。

覆盖：
- repo find_all_by_creator / count_by_creator 仅返回创建者自己的 Skill
- _require_owned：owner 通过，非 owner / 不存在 → 404
- create 强制 is_published=False / requires_approval=True，并写 created_by
- delete 拒绝已发布 Skill（409）
- submit-review：owner 可提、非 owner 404、重复 409
- 路由契约：(method, path) 集合锁定
"""

import io
import uuid
import zipfile

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from starlette.datastructures import UploadFile

from api.v1 import contributor_skills as cs
from core.database import get_worker_session_factory
from models.db import PublishReview, Skill, SkillVersion, User


def _session():
    return get_worker_session_factory()()


async def _two_user_ids() -> tuple[int, int]:
    async with _session() as s:
        result = await s.execute(select(User.id).limit(2))
        ids = [int(r) for r in result.scalars().all()]
        assert len(ids) >= 2, "测试需至少两个真实用户"
        return ids[0], ids[1]


def _fake_zip(name: str) -> UploadFile:
    """构造合法 zip（含 SKILL.md，frontmatter name 与 skill name 一致），过包校验 + 协议校验。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{name}/SKILL.md",
            f"---\nname: {name}\ndescription: test skill\n---\n# {name}\n\ntest body\n",
        )
    buf.seek(0)
    return UploadFile(file=buf, filename=f"{name}.zip")


async def _create_via_router(owner_id: int, name: str | None = None) -> dict:
    """直接调 router 函数；Form() 默认是 FieldInfo，须显式传全部 Form 参数。"""
    session = _session()
    try:
        name = name or f"c{uuid.uuid4().hex[:10]}"
        data = await cs.create_my_skill(
            name=name,
            icon="📦",
            icon_url=None,
            description="",
            category="general",
            version="1.0.0",
            tags="[]",
            author="tester",
            agent_install_prompt="",
            usage_instructions="",
            visibility_type="all",
            source_url="",
            zip_file=_fake_zip(name),
            session=session,
            current_user={
                "id": owner_id,
                "is_admin": False,
                "permissions": ["skill:contribute"],
            },
        )
    finally:
        await session.close()
    return data["data"]


async def _cleanup_skill(skill_id: int) -> None:
    async with _session() as s:
        await s.execute(
            delete(PublishReview).where(PublishReview.entity_id == skill_id)
        )
        await s.execute(delete(SkillVersion).where(SkillVersion.skill_id == skill_id))
        await s.execute(delete(Skill).where(Skill.id == skill_id))
        await s.commit()


@pytest.mark.asyncio
async def test_repo_creator_filter_returns_only_own_skills():
    owner, other = await _two_user_ids()
    created = await _create_via_router(owner)
    skill_id = int(created["id"])
    try:
        async with _session() as s:
            own = await cs.skill_repo.find_all_by_creator(s, owner, 1, 50)
            own_ids = {sk.id for sk in own}
            other_list = await cs.skill_repo.find_all_by_creator(s, other, 1, 50)
            other_ids = {sk.id for sk in other_list}
            assert skill_id in own_ids
            assert skill_id not in other_ids
            assert await cs.skill_repo.count_by_creator(s, owner) >= 1
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_require_owned_owner_passes_non_owner_404():
    owner, other = await _two_user_ids()
    created = await _create_via_router(owner)
    skill_id = int(created["id"])
    try:
        async with _session() as s:
            skill = await cs._require_owned(s, skill_id, owner)
            assert skill.id == skill_id
            with pytest.raises(HTTPException) as exc:
                await cs._require_owned(s, skill_id, other)
            assert exc.value.status_code == 404
            with pytest.raises(HTTPException) as exc2:
                await cs._require_owned(s, skill_id + 999999, owner)
            assert exc2.value.status_code == 404
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_create_forces_draft_and_sets_created_by():
    owner, _ = await _two_user_ids()
    created = await _create_via_router(owner)
    skill_id = int(created["id"])
    try:
        assert created["is_published"] is False
        assert created["requires_approval"] is True
        assert created["created_by"] == owner
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_delete_blocks_published_skill():
    owner, _ = await _two_user_ids()
    created = await _create_via_router(owner)
    skill_id = int(created["id"])
    try:
        async with _session() as s:
            await cs.skill_service.set_published(s, skill_id, True)
            await s.commit()

        session = _session()
        with pytest.raises(HTTPException) as exc:
            await cs.delete_my_skill(
                skill_id,
                session=session,
                current_user={
                    "id": owner,
                    "is_admin": False,
                    "permissions": ["skill:contribute"],
                },
            )
        await session.close()
        assert exc.value.status_code == 409
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_submit_review_owner_non_owner_duplicate():
    owner, other = await _two_user_ids()
    created = await _create_via_router(owner)
    skill_id = int(created["id"])
    try:
        session = _session()
        review = await cs.submit_my_skill_review(
            skill_id,
            session=session,
            current_user={
                "id": owner,
                "is_admin": False,
                "permissions": ["skill:contribute"],
            },
        )
        await session.close()
        assert review["data"]["status"] == "pending"

        session = _session()
        with pytest.raises(HTTPException) as exc:
            await cs.submit_my_skill_review(
                skill_id,
                session=session,
                current_user={
                    "id": other,
                    "is_admin": False,
                    "permissions": ["skill:contribute"],
                },
            )
        await session.close()
        assert exc.value.status_code == 404

        session = _session()
        with pytest.raises(HTTPException) as exc2:
            await cs.submit_my_skill_review(
                skill_id,
                session=session,
                current_user={
                    "id": owner,
                    "is_admin": False,
                    "permissions": ["skill:contribute"],
                },
            )
        await session.close()
        assert exc2.value.status_code == 409
    finally:
        await _cleanup_skill(skill_id)


def test_contributor_routes_contract():
    routes = {(sorted(r.methods)[0], r.path) for r in cs.router.routes}
    assert routes == {
        ("GET", "/contributor/skills"),
        ("GET", "/contributor/skills/{skill_id}"),
        ("POST", "/contributor/skills"),
        ("PUT", "/contributor/skills/{skill_id}"),
        ("DELETE", "/contributor/skills/{skill_id}"),
        ("POST", "/contributor/skills/{skill_id}/versions"),
        ("POST", "/contributor/skills/{skill_id}/submit-review"),
    }
