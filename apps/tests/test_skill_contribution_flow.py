"""贡献者上传编排流程测试（需求 3/4：上传即激活提审、部门可见、下载收口）。

走真实 DB + 直接调 router/service（依赖 dev 中间件运行）。覆盖：
- 上传自动激活 v1（is_active + lifecycle published）并自动提审（pending）
- 脏包（协议不过）上传 400，不落库
- 版本上传自动激活新版（激活跟随最新版）
- owner 设激活端点：可切换；非 owner 404
- 部门可见：department 类型仅本部门成员列表可见
- 下载收口：非 admin 请求非激活版本 404，admin 放行
"""

import io
import uuid
import zipfile

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from starlette.datastructures import UploadFile

from api.v1 import contributor_skills as cs
from api.v1 import skills as admin_skills
from core.database import get_worker_session_factory
from models.db import (
    Department,
    PublishReview,
    Skill,
    SkillVersion,
    User,
    UserDepartment,
)
from services import skill_service


def _session():
    return get_worker_session_factory()()


async def _two_user_ids() -> tuple[int, int]:
    async with _session() as s:
        result = await s.execute(select(User.id).limit(2))
        ids = [int(r) for r in result.scalars().all()]
        assert len(ids) >= 2, "测试需至少两个真实用户"
        return ids[0], ids[1]


def _fake_zip(name: str) -> UploadFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{name}/SKILL.md",
            f"---\nname: {name}\ndescription: test skill\n---\n# {name}\n\ntest body\n",
        )
    buf.seek(0)
    return UploadFile(file=buf, filename=f"{name}.zip")


def _broken_zip() -> UploadFile:
    """有 SKILL.md 但 frontmatter name 非 kebab-case（协议 error 级）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "bad/SKILL.md",
            "---\nname: BadName\ndescription: test\n---\n# bad\n",
        )
    buf.seek(0)
    return UploadFile(file=buf, filename="bad.zip")


async def _create_via_router(owner_id: int, name: str | None = None) -> dict:
    session = _session()
    try:
        name = name or f"f{uuid.uuid4().hex[:10]}"
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
            visibility_type=None,
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

    async with _session() as s:
        paths = []
        skill = await s.get(Skill, skill_id)
        if skill:
            paths.append(skill.zip_path)
            for v in skill.versions or []:
                paths.append(v.zip_path)
        result = await s.execute(
            select(SkillVersion.id).where(SkillVersion.skill_id == skill_id)
        )
        assert result.scalars().first() is not None
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
async def test_upload_auto_activates_and_submits_review():
    owner, _ = await _two_user_ids()
    created = await _create_via_router(owner)
    skill_id = int(created["id"])
    try:
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            version = await s.get(SkillVersion, skill.current_version_id)
            assert version.is_active is True
            assert version.lifecycle_status == "published"
            review = await s.execute(
                select(PublishReview).where(
                    PublishReview.entity_type == "skill",
                    PublishReview.entity_id == skill_id,
                )
            )
            assert review.scalar_one().status == "pending"
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_upload_explicit_visibility_all_respected():
    """web 表单显式传 all → 尊重调用方（默认 department 只在不传时生效）。"""
    owner, _ = await _two_user_ids()
    session = _session()
    name = f"vis{uuid.uuid4().hex[:8]}"
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
            "id": owner,
            "is_admin": False,
            "permissions": ["skill:contribute"],
        },
    )
    await session.close()
    skill_id = int(data["data"]["id"])
    try:
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            assert skill.visibility_type == "all"
            assert skill.visible_department_id is None
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_upload_broken_package_rejected_no_row():
    owner, _ = await _two_user_ids()
    name = f"bad{uuid.uuid4().hex[:8]}"
    session = _session()
    with pytest.raises(HTTPException) as exc:
        await cs.create_my_skill(
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
            visibility_type=None,
            source_url="",
            zip_file=_broken_zip(),
            session=session,
            current_user={
                "id": owner,
                "is_admin": False,
                "permissions": ["skill:contribute"],
            },
        )
    await session.close()
    assert exc.value.status_code == 400
    async with _session() as s:
        result = await s.execute(select(Skill.id).where(Skill.name == name))
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_version_upload_auto_activates_latest():
    owner, _ = await _two_user_ids()
    created = await _create_via_router(owner)
    skill_id = int(created["id"])
    try:
        session = _session()
        v2 = await cs.create_my_skill_version(
            skill_id,
            version="1.0.1",
            version_label="",
            change_log="bump",
            zip_file=_fake_zip("x"),
            session=session,
            current_user={
                "id": owner,
                "is_admin": False,
                "permissions": ["skill:contribute"],
            },
        )
        await session.close()
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            assert skill.current_version_id == v2["data"]["id"]
            v1 = await s.get(SkillVersion, created["current_version_id"])
            v2row = await s.get(SkillVersion, v2["data"]["id"])
            assert v1.is_active is False
            assert v2row.is_active is True
            assert v2row.lifecycle_status == "published"
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_owner_can_switch_active_version_non_owner_404():
    owner, other = await _two_user_ids()
    created = await _create_via_router(owner)
    skill_id = int(created["id"])
    v1_id = int(created["current_version_id"])
    try:
        session = _session()
        v2 = await cs.create_my_skill_version(
            skill_id,
            version="2.0.0",
            version_label="",
            change_log="",
            zip_file=_fake_zip("x"),
            session=session,
            current_user={
                "id": owner,
                "is_admin": False,
                "permissions": ["skill:contribute"],
            },
        )
        await session.close()

        session = _session()
        switched = await cs.activate_my_skill_version(
            skill_id,
            v1_id,
            session=session,
            current_user={
                "id": owner,
                "is_admin": False,
                "permissions": ["skill:contribute"],
            },
        )
        await session.close()
        assert switched["data"]["current_version_id"] == v1_id

        session = _session()
        with pytest.raises(HTTPException) as exc:
            await cs.activate_my_skill_version(
                skill_id,
                v2["data"]["id"],
                session=session,
                current_user={
                    "id": other,
                    "is_admin": False,
                    "permissions": ["skill:contribute"],
                },
            )
        await session.close()
        assert exc.value.status_code == 404
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_department_visibility_filters_market_list():
    """department 可见：本部门成员列表可见，非成员不可见；发布后同步部门主 Key。"""
    owner, other = await _two_user_ids()
    async with _session() as s:
        dept = Department(name=f"t-dept-{uuid.uuid4().hex[:6]}")
        s.add(dept)
        await s.flush()
        dept_id = dept.id
        s.add(UserDepartment(user_id=owner, department_id=dept_id))
        await s.commit()
    created = await _create_via_router(owner)
    skill_id = int(created["id"])
    try:
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            assert skill.visibility_type == "department"
            # 默认部门 = owner 最早加入部门（真实用户可能已有更早部门，不钦定测试部门）
            assert skill.visible_department_id is not None
            owner_dept_ids = [
                int(r)
                for r in (
                    await s.execute(
                        select(UserDepartment.department_id).where(
                            UserDepartment.user_id == owner
                        )
                    )
                )
                .scalars()
                .all()
            ]
            assert skill.visible_department_id in owner_dept_ids
            await skill_service.set_published(s, skill_id, True)
            await s.commit()

        in_list = await skill_service.list_skills(
            _session(),
            is_published=True,
            viewer_id=owner,
            is_admin=False,
            viewer_department_ids=owner_dept_ids,
        )
        assert skill_id in {item["id"] for item in in_list["items"]}
        outsider = await skill_service.list_skills(
            _session(),
            is_published=True,
            viewer_id=other,
            is_admin=False,
            viewer_department_ids=[],
        )
        assert skill_id not in {item["id"] for item in outsider["items"]}
    finally:
        await _cleanup_skill(skill_id)
        async with _session() as s:
            await s.execute(
                delete(UserDepartment).where(UserDepartment.department_id == dept_id)
            )
            await s.execute(delete(Department).where(Department.id == dept_id))
            await s.commit()


@pytest.mark.asyncio
async def test_download_inactive_version_blocked_for_non_admin():
    owner, _ = await _two_user_ids()
    created = await _create_via_router(owner)
    skill_id = int(created["id"])
    v1_id = int(created["current_version_id"])
    try:
        session = _session()
        await cs.create_my_skill_version(
            skill_id,
            version="3.0.0",
            version_label="",
            change_log="",
            zip_file=_fake_zip("x"),
            session=session,
            current_user={
                "id": owner,
                "is_admin": False,
                "permissions": ["skill:contribute"],
            },
        )
        await session.close()

        # 非 admin 下历史（非激活）版本 → 404；admin 同请求放行
        session = _session()
        with pytest.raises(HTTPException) as exc:
            await admin_skills.download_skill(
                skill_id,
                version_id=v1_id,
                session=session,
                current_user={
                    "id": owner,
                    "is_admin": False,
                    "permissions": ["skill:read"],
                },
            )
        await session.close()
        assert exc.value.status_code == 404

        session = _session()
        admin_resp = await admin_skills.download_skill(
            skill_id,
            version_id=v1_id,
            session=session,
            current_user={"id": owner, "is_admin": True, "permissions": []},
        )
        await session.close()
        assert admin_resp is not None
    finally:
        await _cleanup_skill(skill_id)


@pytest.mark.asyncio
async def test_view_version_id_blocked_for_non_admin():
    """summary/full 视图同 download 收口：非 admin 指定 version_id → 404，admin 放行。"""
    owner, _ = await _two_user_ids()
    created = await _create_via_router(owner)
    skill_id = int(created["id"])
    v1_id = int(created["current_version_id"])
    try:
        session = _session()
        await cs.create_my_skill_version(
            skill_id,
            version="4.0.0",
            version_label="",
            change_log="",
            zip_file=_fake_zip("x"),
            session=session,
            current_user={
                "id": owner,
                "is_admin": False,
                "permissions": ["skill:contribute"],
            },
        )
        await session.close()

        for view_call in (admin_skills.get_skill_summary, admin_skills.get_skill_full):
            session = _session()
            with pytest.raises(HTTPException) as exc:
                await view_call(
                    skill_id,
                    version_id=v1_id,
                    session=session,
                    current_user={
                        "id": owner,
                        "is_admin": False,
                        "permissions": ["skill:read"],
                    },
                )
            await session.close()
            assert exc.value.status_code == 404

            session = _session()
            data = await view_call(
                skill_id,
                version_id=v1_id,
                session=session,
                current_user={"id": owner, "is_admin": True, "permissions": []},
            )
            await session.close()
            assert data["code"] == 200
    finally:
        await _cleanup_skill(skill_id)
