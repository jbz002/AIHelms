"""Skill 分类硬枚举测试（迁移 089 + skill_service._validate_category）。

走真实 DB + 直接调 router/service（同 test_skill_contribution_flow 形态）。覆盖：
- 合法分类（标准六类）创建成功且原样落库
- 未知分类 400，detail 枚举「有效分类」清单（ai-assistant 透传给 agent 自纠重试）
- 遗留别名归一：'general' → '通用'（部署窗口容错，不 400）
- update_skill 换非法分类 400（admin API / 贡献者 PUT / mcp_admin 共用该路径）
- delete_category 引用检查：分类下有 Skill → 409；空分类可删
- GET /skills/categories 放权后函数签名不再依赖 skill:read 身份
前置：dev 库已跑 089（通用/编程开发等标准类在注册表）。
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from starlette.datastructures import UploadFile

from api.v1 import contributor_skills as cs
from api.v1 import skills as admin_skills
from core.database import get_worker_session_factory
from exceptions import ConflictError, ValidationError
from models.db import Skill, SkillVersion, User
from services import skill_service


def _session():
    return get_worker_session_factory()()


def _fake_zip(name: str) -> UploadFile:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{name}/SKILL.md",
            f"---\nname: {name}\ndescription: test skill\n---\n# {name}\n\ntest body\n",
        )
    buf.seek(0)
    return UploadFile(file=buf, filename=f"{name}.zip")


async def _owner_id() -> int:
    async with _session() as s:
        result = await s.execute(select(User.id).limit(1))
        uid = result.scalars().first()
        assert uid is not None, "测试需至少一个真实用户"
        return int(uid)


async def _create(owner_id: int, category: str, name: str | None = None) -> dict:
    name = name or f"cat{uuid.uuid4().hex[:10]}"
    session = _session()
    try:
        data = await cs.create_my_skill(
            name=name,
            icon="📦",
            icon_url=None,
            description="",
            category=category,
            version="1.0.0",
            tags='["测试关键词"]',
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
    import os

    from models.db import PublishReview

    async with _session() as s:
        skill = await s.get(Skill, skill_id)
        paths = [skill.zip_path] if skill else []
        if skill:
            for v in skill.versions or []:
                paths.append(v.zip_path)
        await s.execute(
            delete(PublishReview).where(
                PublishReview.entity_type == "skill",
                PublishReview.entity_id == skill_id,
            )
        )
        await s.execute(delete(SkillVersion).where(SkillVersion.skill_id == skill_id))
        await s.execute(delete(Skill).where(Skill.id == skill_id))
        await s.commit()
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_valid_category_stored_verbatim():
    owner = await _owner_id()
    created = await _create(owner, category="编程开发")
    skill_id = int(created["id"])
    try:
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            assert skill.category == "编程开发"
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_unknown_category_400_enumerates_valid():
    owner = await _owner_id()
    name = f"bad{uuid.uuid4().hex[:8]}"
    session = _session()
    with pytest.raises(HTTPException) as exc:
        await cs.create_my_skill(
            name=name,
            icon="📦",
            icon_url=None,
            description="",
            category="不存在的分类",
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
                "id": owner,
                "is_admin": False,
                "permissions": ["skill:contribute"],
            },
        )
    await session.close()
    assert exc.value.status_code == 400
    # 400 detail 枚举有效分类——ai-assistant _contribute_error 原样透传给 agent 自纠
    assert "有效分类" in str(exc.value.detail)
    assert "通用" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_legacy_general_alias_normalized():
    """未升级 ai-assistant（默认发 'general'）在部署窗口不 400，落库即标准名。"""
    owner = await _owner_id()
    created = await _create(owner, category="general")
    skill_id = int(created["id"])
    try:
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            assert skill.category == "通用"
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_update_invalid_category_400():
    """update_skill 换非法分类 400（admin PUT / 贡献者 PUT / mcp_admin 共用路径）。"""
    owner = await _owner_id()
    created = await _create(owner, category="通用")
    skill_id = int(created["id"])
    try:
        async with _session() as s:
            with pytest.raises(ValidationError):
                await skill_service.update_skill(
                    s, skill_id, actor_is_admin=True, category="垃圾分类"
                )
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_delete_category_in_use_conflict():
    """引用检查：分类下有 Skill → 409；清空后可删。"""
    from repositories import skill_repo

    owner = await _owner_id()
    cat_name = f"tmp分类{uuid.uuid4().hex[:6]}"
    session = _session()
    await skill_service.create_category(session, name=cat_name, sort_order=999)
    await session.close()

    created = await _create(owner, category=cat_name)
    skill_id = int(created["id"])
    try:
        async with _session() as s:
            cat = await skill_repo.find_category_by_name(s, cat_name)
            assert cat is not None
            with pytest.raises(ConflictError):
                await skill_service.delete_category(s, cat.id)

        await _cleanup_skill(skill_id)

        async with _session() as s:
            cat = await skill_repo.find_category_by_name(s, cat_name)
            assert cat is not None
            await skill_service.delete_category(s, cat.id)  # 清空后可删
    finally:
        await _cleanup_skill(skill_id)
        async with _session() as s:
            cat = await skill_repo.find_category_by_name(s, cat_name)
            if cat:
                await skill_repo.delete_category(s, cat.id)
                await s.commit()


@pytest.mark.asyncio
async def test_categories_endpoint_plain_identity():
    """GET /skills/categories 放权后：普通身份（无 skill:read）可直接读分类枚举。"""
    async with _session() as s:
        resp = await admin_skills.list_categories(
            session=s, _={"id": 1, "is_admin": False, "permissions": []}
        )
    assert resp["code"] == 200
    names = [c["name"] for c in resp["data"]]
    assert "通用" in names
