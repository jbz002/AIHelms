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


async def get_skill_summary(session: AsyncSession, skill_id: int) -> dict:
    """Summary view: summary_text + frontmatter from active version."""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    active = await skill_version_repo.find_active_for_skill(session, skill_id)
    summary = active.summary_text if active else skill.summary_text
    fm = active.frontmatter if active else skill.frontmatter
    return {
        "id": skill.id,
        "name": skill.name,
        "frontmatter": fm,
        "summary_text": summary,
    }


async def get_skill_full(session: AsyncSession, skill_id: int) -> dict:
    """Full view: complete content + file hashes from active version."""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    active = await skill_version_repo.find_active_for_skill(session, skill_id)
    if not active:
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
        "frontmatter": active.frontmatter,
        "summary_text": active.summary_text,
        "full_content": active.full_content,
        "file_hashes": active.file_hashes,
        "composite_hash": active.composite_hash,
    }


async def get_skill_integrity(session: AsyncSession, skill_id: int) -> dict:
    """Integrity view: hashes + drift status. Admin only."""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
    active = await skill_version_repo.find_active_for_skill(session, skill_id)
    if not active:
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
        "version_id": active.id,
        "version": active.version,
        "source_type": active.source_type,
        "composite_hash": active.composite_hash,
        "content_sha256": active.content_sha256,
        "file_hashes": active.file_hashes,
        "drift_detected": active.drift_detected,
        "drifted_files": active.drifted_files,
        "last_drift_check_at": (
            active.last_drift_check_at.isoformat()
            if active.last_drift_check_at
            else None
        ),
        "drift_check_error": active.drift_check_error or "",
        "protocol_valid": active.protocol_valid,
        "protocol_errors": active.protocol_errors,
    }
