"""Skill view service — three-layer progressive disclosure + integrity.

Reads from the active version's pre-computed content fields.
Zero parsing overhead at query time.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from repositories import skill_repo, skill_version_repo

logger = logging.getLogger(__name__)


async def get_skill_card(session: AsyncSession, skill_id: int) -> dict:
    """Card view: reads from Skill table directly (zero join)."""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    return {
        "id": skill.id,
        "skill_id": skill.skill_id,
        "name": skill.name,
        "icon": skill.icon,
        "description": skill.description,
        "version": skill.version,
        "category": skill.category,
        "tags": skill.tags,
        "author": skill.author,
        "frontmatter": skill.frontmatter,
        "summary_text": skill.summary_text,
        "install_count": skill.install_count,
        "is_published": skill.is_published,
    }


async def _resolve_version(
    session: AsyncSession, skill_id: int, version_id: int | None
):
    """选定版本解析：version_id 给定则按 id 取（校验归属），否则取 active。

    返回 (version_or_none, used_version_id)。version_id 给定但无效时抛 NotFoundError。
    """
    if version_id is not None:
        version = await skill_version_repo.find_owned_by_skill(
            session, version_id, skill_id
        )
        if not version:
            raise NotFoundError("skill_version", version_id)
        return version
    return await skill_version_repo.find_active_for_skill(session, skill_id)


async def get_skill_summary(
    session: AsyncSession, skill_id: int, version_id: int | None = None
) -> dict:
    """Summary view: summary_text + frontmatter from selected (or active) version."""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    version = await _resolve_version(session, skill_id, version_id)
    summary = version.summary_text if version else skill.summary_text
    fm = version.frontmatter if version else skill.frontmatter
    return {
        "id": skill.id,
        "name": skill.name,
        "frontmatter": fm,
        "summary_text": summary,
    }


async def get_skill_full(
    session: AsyncSession, skill_id: int, version_id: int | None = None
) -> dict:
    """Full view: complete content + file hashes from selected (or active) version."""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    version = await _resolve_version(session, skill_id, version_id)
    if not version:
        return {
            "id": skill.id,
            "name": skill.name,
            "frontmatter": skill.frontmatter,
            "summary_text": skill.summary_text,
            "full_content": "",
            "file_hashes": {},
            "composite_hash": "",
        }
    return {
        "id": skill.id,
        "name": skill.name,
        "frontmatter": version.frontmatter,
        "summary_text": version.summary_text,
        "full_content": version.full_content,
        "file_hashes": version.file_hashes,
        "composite_hash": version.composite_hash,
    }


async def get_skill_integrity(
    session: AsyncSession, skill_id: int, version_id: int | None = None
) -> dict:
    """Integrity view: hashes + drift status. Admin only."""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    version = await _resolve_version(session, skill_id, version_id)
    if not version:
        return {
            "skill_id": skill.id,
            "version": "",
            "source_type": "zip",
            "composite_hash": "",
            "content_sha256": "",
            "file_hashes": {},
            "drift_detected": False,
            "drifted_files": [],
            "last_drift_check_at": None,
            "drift_check_error": "",
            "protocol_valid": False,
            "protocol_errors": [],
            "version_id": None,
        }
    return {
        "skill_id": skill.id,
        "version_id": version.id,
        "version": version.version,
        "source_type": version.source_type,
        "composite_hash": version.composite_hash,
        "content_sha256": version.content_sha256,
        "file_hashes": version.file_hashes,
        "drift_detected": version.drift_detected,
        "drifted_files": version.drifted_files,
        "last_drift_check_at": (
            version.last_drift_check_at.isoformat()
            if version.last_drift_check_at
            else None
        ),
        "drift_check_error": version.drift_check_error or "",
        "protocol_valid": version.protocol_valid,
        "protocol_errors": version.protocol_errors,
    }
