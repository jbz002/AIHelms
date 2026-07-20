"""Skill serializers — convert ORM models to API dicts.

Extracted from skill_service.py to keep it under the 500-line limit.
"""

from __future__ import annotations

from models.db import Skill, SkillVersion
from repositories import ai_policies_repo


async def _latest_audit_map(session, skills: list[Skill]) -> dict[int, str]:
    audit_ids = [
        skill.latest_ai_policies_audit_id
        for skill in skills
        if skill.latest_ai_policies_audit_id
    ]
    audits = await ai_policies_repo.find_by_ids(session, audit_ids)
    return {audit.id: audit.audit_id for audit in audits}


def _serialize_version(v: SkillVersion) -> dict:
    return {
        "id": v.id,
        "skill_id": v.skill_id,
        "version": v.version,
        "version_label": v.version_label,
        "is_active": v.is_active,
        "lifecycle_status": v.lifecycle_status,
        "sunset_date": v.sunset_date.isoformat() if v.sunset_date else None,
        "source": v.source,
        "source_type": v.source_type,
        "zip_size": v.zip_size,
        "zip_filename": v.zip_filename,
        "change_log": v.change_log,
        "frontmatter": v.frontmatter,
        "summary_text": v.summary_text,
        "composite_hash": v.composite_hash,
        "file_hashes": v.file_hashes,
        "drift_detected": v.drift_detected,
        "security_status": v.security_status,
        "security_decision": v.security_decision,
        "latest_ai_policies_audit_id": v.latest_ai_policies_audit_id,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


def _serialize(skill: Skill, latest_audit_map: dict[int, str] | None = None) -> dict:
    latest_audit_map = latest_audit_map or {}
    latest_audit_code = (
        latest_audit_map.get(skill.latest_ai_policies_audit_id)
        if skill.latest_ai_policies_audit_id
        else None
    )
    active = next((v for v in (skill.versions or []) if v.is_active), None)
    return {
        "id": skill.id,
        "skill_id": skill.skill_id,
        "name": skill.name,
        "icon": skill.icon,
        "description": skill.description,
        "category": skill.category,
        "version": skill.version,
        "tags": skill.tags,
        "author": skill.author,
        "agent_install_prompt": skill.agent_install_prompt,
        "usage_instructions": skill.usage_instructions,
        "zip_path": skill.zip_path,
        "zip_size": skill.zip_size,
        "zip_filename": skill.zip_filename,
        "has_zip": bool(skill.zip_path),
        "is_active": skill.is_active,
        "is_published": skill.is_published,
        "requires_approval": skill.requires_approval,
        "install_count": skill.install_count,
        "frontmatter": skill.frontmatter,
        "summary_text": skill.summary_text,
        "security_status": skill.security_status,
        "security_decision": skill.security_decision,
        "security_severity": skill.security_severity,
        "security_risk_score": skill.security_risk_score,
        "latest_ai_policies_audit_id": skill.latest_ai_policies_audit_id,
        "latest_ai_policies_audit_code": latest_audit_code,
        "current_version_id": skill.current_version_id,
        "active_version": _serialize_version(active) if active else None,
        "created_by": skill.created_by,
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }
