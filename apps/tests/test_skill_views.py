"""Skill 视图集成测试 — card/summary/full/integrity.

走真实 DB（依赖 dev 中间件运行），覆盖渐进式披露三层视图和完整性信息端点。
"""

import io
import zipfile

import pytest
from sqlalchemy import delete

from core.database import get_worker_session_factory
from models.db import Skill, SkillVersion
from repositories import skill_repo, skill_version_repo
from services import skill_service, skill_view_service


def _session():
    return get_worker_session_factory()()


def _make_valid_zip(name: str = "test-skill") -> bytes:
    """Create a minimal valid ZIP with SKILL.md for testing."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        content = (
            f"---\nname: {name}\n"
            f"description: A test skill for views\n"
            f"---\n\n# {name}\n\n"
            "First paragraph of instructions.\n"
            "Second paragraph of details.\n"
        )
        zf.writestr("SKILL.md", content)
    return buf.getvalue()


async def _make_skill_with_content(suffix: str | None = None) -> tuple[int, str]:
    name = f"test_vw_{(suffix or 'default')[:12]}"
    session = _session()
    try:
        data = await skill_service.create_skill(
            session,
            name=name,
            description="desc",
            version="1.0.0",
            zip_content=_make_valid_zip(name),
            zip_filename=f"{name}.zip",
        )
    finally:
        await session.close()
    return data["id"], data["skill_id"]


async def _cleanup(skill_ids: list[int]) -> None:
    session = _session()
    try:
        for sid in skill_ids:
            await session.execute(
                delete(SkillVersion).where(SkillVersion.skill_id == sid)
            )
            await session.execute(delete(Skill).where(Skill.id == sid))
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_get_skill_card_returns_frontmatter():
    skill_id, _ = await _make_skill_with_content("card")
    session = _session()
    try:
        card = await skill_view_service.get_skill_card(session, skill_id)
        assert card["id"] == skill_id
        assert card["name"] == "test_vw_card"
        assert isinstance(card["frontmatter"], dict)
        assert "description" in card["frontmatter"]
        assert "summary_text" in card
    finally:
        await session.close()
    await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_get_skill_summary_returns_parsed_content():
    skill_id, _ = await _make_skill_with_content("summary")
    session = _session()
    try:
        data = await skill_view_service.get_skill_summary(session, skill_id)
        assert data["id"] == skill_id
        assert isinstance(data["frontmatter"], dict)
        assert "First paragraph" in data["summary_text"]
    finally:
        await session.close()
    await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_get_skill_full_returns_full_content():
    skill_id, _ = await _make_skill_with_content("full")
    session = _session()
    try:
        data = await skill_view_service.get_skill_full(session, skill_id)
        assert data["id"] == skill_id
        assert "First paragraph" in data["full_content"]
        assert "Second paragraph" in data["full_content"]
        assert isinstance(data["file_hashes"], dict)
        assert data["composite_hash"] != ""
    finally:
        await session.close()
    await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_get_skill_integrity_returns_hashes():
    skill_id, _ = await _make_skill_with_content("integrity")
    session = _session()
    try:
        data = await skill_view_service.get_skill_integrity(session, skill_id)
        assert data["skill_id"] == skill_id
        assert data["source_type"] == "zip"
        assert data["composite_hash"] != ""
        assert isinstance(data["file_hashes"], dict)
        assert data["drift_detected"] is False
    finally:
        await session.close()
    await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_skill_creation_populates_content_fields():
    """create_skill parses SKILL.md and writes content to version + skill."""
    skill_id, _ = await _make_skill_with_content("parse")
    session = _session()
    try:
        skill = await skill_repo.find_by_id(session, skill_id)
        assert skill is not None
        # Master table snapshot should have frontmatter
        assert skill.frontmatter is not None
        assert skill.summary_text != ""
        # Active version should have content
        active = await skill_version_repo.find_active_for_skill(session, skill_id)
        assert active is not None
        assert active.frontmatter is not None
        assert active.full_content != ""
        assert active.composite_hash != ""
    finally:
        await session.close()
    await _cleanup([skill_id])
