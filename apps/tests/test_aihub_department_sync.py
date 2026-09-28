"""AI Hub 全量部门同步 + Skill 按部门可见字段更新测试（走真实 DB）。

覆盖：
- sync_departments：全量 upsert（插入/改名/幂等）+ dingtalk 父链映射本地 parent_id
- list_full_departments：拉取失败降级返回本地列表
- update_skill：visible_department_id 设置 / 0=清空 / 部门不存在 400 / 按部门缺部门 400
"""

import io
import uuid
import zipfile

import pytest
from sqlalchemy import delete, select

from core.database import get_worker_session_factory
from exceptions import ValidationError
from models.db import Department, PublishReview, Skill, SkillVersion
from services import aihub_department_service, skill_service


def _session():
    return get_worker_session_factory()()


#: 三层部门树：总部 ← 研发部 ← 后端组（dingtalk id 层级）
_FIXTURE = [
    {
        "id": "syncroot0000000000000001",
        "name": "同步测试总部",
        "dingtalk_dept_id": 990001,
        "parent_dingtalk_dept_id": None,
    },
    {
        "id": "syncroot0000000000000002",
        "name": "同步测试研发部",
        "dingtalk_dept_id": 990002,
        "parent_dingtalk_dept_id": 990001,
    },
    {
        "id": "syncroot0000000000000003",
        "name": "同步测试后端组",
        "dingtalk_dept_id": 990003,
        "parent_dingtalk_dept_id": 990002,
    },
]
_FIXTURE_IDS = [d["id"] for d in _FIXTURE]


@pytest.fixture(autouse=True)
def _fresh_sync_state(monkeypatch):
    """每个测试重置 TTL 节流状态 + 注入固定拉取结果。"""
    monkeypatch.setattr(aihub_department_service, "_last_sync_ok_at", 0.0)
    monkeypatch.setattr(aihub_department_service, "_last_sync_fail_at", 0.0)
    monkeypatch.setattr(
        aihub_department_service,
        "fetch_aihub_departments",
        _raise_fetch_unavailable,
    )
    yield


async def _raise_fetch_unavailable() -> list[dict]:
    raise aihub_department_service.AIHubDepartmentError("测试环境不外呼")


async def _fetch_fixture(override: list[dict] | None = None) -> list[dict]:
    return override if override is not None else _FIXTURE


async def _cleanup_departments() -> None:
    async with _session() as s:
        await s.execute(
            delete(Department).where(Department.aihub_department_id.in_(_FIXTURE_IDS))
        )
        await s.commit()


async def _dept_by_aihub_id(aihub_id: str) -> Department | None:
    async with _session() as s:
        result = await s.execute(
            select(Department).where(Department.aihub_department_id == aihub_id)
        )
        return result.scalar_one_or_none()


# ─── sync_departments ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_inserts_and_links_parents(monkeypatch):
    monkeypatch.setattr(
        aihub_department_service, "fetch_aihub_departments", _fetch_fixture
    )
    try:
        session = _session()
        try:
            stats = await aihub_department_service.sync_departments(session)
        finally:
            await session.close()
        assert stats["inserted"] == 3
        assert stats["fetched"] == 3

        root = await _dept_by_aihub_id(_FIXTURE[0]["id"])
        dev = await _dept_by_aihub_id(_FIXTURE[1]["id"])
        backend = await _dept_by_aihub_id(_FIXTURE[2]["id"])
        assert root is not None and dev is not None and backend is not None
        assert root.parent_id is None  # 公司根不在返回集合 → 顶级
        assert dev.parent_id == root.id
        assert backend.parent_id == dev.id
    finally:
        await _cleanup_departments()


@pytest.mark.asyncio
async def test_sync_idempotent_and_renames(monkeypatch):
    monkeypatch.setattr(
        aihub_department_service, "fetch_aihub_departments", _fetch_fixture
    )
    try:
        session = _session()
        try:
            first = await aihub_department_service.sync_departments(session)
        finally:
            await session.close()

        renamed = [dict(_FIXTURE[0], name="同步测试总部改"), *_FIXTURE[1:]]

        async def _fetch_renamed() -> list[dict]:
            return await _fetch_fixture(renamed)

        monkeypatch.setattr(
            aihub_department_service, "fetch_aihub_departments", _fetch_renamed
        )
        session = _session()
        try:
            second = await aihub_department_service.sync_departments(session)
        finally:
            await session.close()

        assert first["inserted"] == 3
        assert second["inserted"] == 0
        assert second["updated"] == 1
        assert second["fetched"] == 3

        root = await _dept_by_aihub_id(_FIXTURE[0]["id"])
        assert root is not None
        assert root.name == "同步测试总部改"
        # 幂等：仍只有 3 条
        async with _session() as s:
            rows = await s.execute(
                select(Department).where(
                    Department.aihub_department_id.in_(_FIXTURE_IDS)
                )
            )
            assert len(rows.scalars().all()) == 3
    finally:
        await _cleanup_departments()


@pytest.mark.asyncio
async def test_list_full_departments_falls_back_to_local():
    """拉取失败（默认 monkeypatch 抛错）时降级返回本地列表，不 raise。"""
    try:
        session = _session()
        try:
            items = await aihub_department_service.list_full_departments(session)
        finally:
            await session.close()
        assert isinstance(items, list)
        assert all("id" in it and "name" in it for it in items)
    finally:
        await _cleanup_departments()


# ─── update_skill visible_department_id ───────────────────────────────────────


def _valid_zip(name: str) -> bytes:
    skill_md = (
        f"---\nname: {name}\ndescription: dept visibility test\n---\n\n# {name}\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", skill_md)
    return buf.getvalue()


async def _make_skill() -> int:
    name = f"dept-vis-{uuid.uuid4().hex[:8]}"
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


async def _cleanup_skill(skill_id: int) -> None:
    async with _session() as s:
        await s.execute(
            delete(PublishReview).where(PublishReview.entity_id == skill_id)
        )
        await s.execute(delete(SkillVersion).where(SkillVersion.skill_id == skill_id))
        await s.execute(delete(Skill).where(Skill.id == skill_id))
        await s.commit()


async def _make_department(name: str) -> int:
    async with _session() as s:
        dept = Department(
            name=name,
            aihub_department_id=f"localtest{uuid.uuid4().hex[:18]}",
            is_active=True,
        )
        s.add(dept)
        await s.commit()
        await s.refresh(dept)
        return dept.id


async def _cleanup_department(dept_id: int) -> None:
    async with _session() as s:
        await s.execute(delete(Department).where(Department.id == dept_id))
        await s.commit()


@pytest.mark.asyncio
async def test_update_skill_sets_and_clears_visible_department():
    dept_id = await _make_department("可见性测试部门")
    skill_id = await _make_skill()
    try:
        session = _session()
        try:
            data = await skill_service.update_skill(
                session,
                skill_id,
                visibility_type="department",
                visible_department_id=dept_id,
                is_published=True,
            )
        finally:
            await session.close()
        assert data["visible_department_id"] == dept_id

        # 切回 all 并传 0 → 清空部门归属
        session = _session()
        try:
            data = await skill_service.update_skill(
                session,
                skill_id,
                visibility_type="all",
                visible_department_id=0,
            )
        finally:
            await session.close()
        assert data["visible_department_id"] is None
    finally:
        await _cleanup_skill(skill_id)
        await _cleanup_department(dept_id)


@pytest.mark.asyncio
async def test_update_skill_rejects_missing_and_unknown_department():
    dept_id = await _make_department("可见性测试部门2")
    skill_id = await _make_skill()
    try:
        # 按部门可见但没给部门 → 400
        session = _session()
        try:
            with pytest.raises(ValidationError):
                await skill_service.update_skill(
                    session, skill_id, visibility_type="department"
                )
        finally:
            await session.close()

        # 部门不存在 → 400
        session = _session()
        try:
            with pytest.raises(ValidationError):
                await skill_service.update_skill(
                    session,
                    skill_id,
                    visibility_type="department",
                    visible_department_id=99999999,
                )
        finally:
            await session.close()
    finally:
        await _cleanup_skill(skill_id)
        await _cleanup_department(dept_id)
