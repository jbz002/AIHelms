"""Skill serializers — convert ORM models to API dicts.

Extracted from skill_service.py to keep it under the 500-line limit.
"""

from __future__ import annotations

from models.db import Skill, SkillReviewTask, SkillVersion
from repositories import ai_policies_repo
from services.skill_lifecycle_projection import build_projection


async def _latest_audit_map(session, skills: list[Skill]) -> dict[int, str]:
    audit_ids = [
        skill.latest_ai_policies_audit_id
        for skill in skills
        if skill.latest_ai_policies_audit_id
    ]
    audits = await ai_policies_repo.find_by_ids(session, audit_ids)
    return {audit.id: audit.audit_id for audit in audits}


def _serialize_version(
    v: SkillVersion,
    tags: list[str] | None = None,
    audit_code: str | None = None,
) -> dict:
    return {
        "id": v.id,
        "skill_id": v.skill_id,
        "version": v.version,
        "version_label": v.version_label,
        "is_active": v.is_active,
        "lifecycle_status": v.lifecycle_status,
        "tags": tags or [],
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
        "drifted_files": v.drifted_files or [],
        "last_drift_check_at": (
            v.last_drift_check_at.isoformat() if v.last_drift_check_at else None
        ),
        "drift_check_error": v.drift_check_error or "",
        "protocol_valid": v.protocol_valid,
        "protocol_errors": v.protocol_errors,
        "last_validated_at": (
            v.last_validated_at.isoformat() if v.last_validated_at else None
        ),
        "security_status": v.security_status,
        "security_decision": v.security_decision,
        "latest_ai_policies_audit_id": v.latest_ai_policies_audit_id,
        "latest_ai_policies_audit_code": audit_code,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


def _serialize_review_task(t: SkillReviewTask) -> dict:
    return {
        "id": t.id,
        "skill_version_id": t.skill_version_id,
        "status": t.status,
        "reviewer_id": t.reviewer_id,
        "submitted_by": t.submitted_by,
        "decision_notes": t.decision_notes,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
    }


def _serialize(
    skill: Skill,
    latest_audit_map: dict[int, str] | None = None,
    labels: list[dict] | None = None,
    version_tags_map: dict[int, list[str]] | None = None,
) -> dict:
    latest_audit_map = latest_audit_map or {}
    latest_audit_code = (
        latest_audit_map.get(skill.latest_ai_policies_audit_id)
        if skill.latest_ai_policies_audit_id
        else None
    )
    active = next((v for v in (skill.versions or []) if v.is_active), None)
    versions_sorted = sorted((skill.versions or []), key=lambda v: v.id, reverse=True)
    serialized_versions = [
        _serialize_version(v, version_tags_map.get(v.id) if version_tags_map else None)
        for v in versions_sorted
    ]
    projection = build_projection(
        serialized_versions, skill.current_version_id, skill.hidden
    )
    return {
        "id": skill.id,
        "skill_id": skill.skill_id,
        "name": skill.name,
        "icon": skill.icon,
        "description": skill.description,
        "category": skill.category,
        "version": skill.version,
        "tags": skill.tags,
        "labels": labels or [],
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
        "visibility_type": skill.visibility_type,
        "hidden": skill.hidden,
        "hidden_at": skill.hidden_at.isoformat() if skill.hidden_at else None,
        "lifecycle_projection": projection,
        "install_count": skill.install_count,
        "frontmatter": skill.frontmatter,
        "summary_text": skill.summary_text,
        "is_builtin": skill.is_builtin,
        "builtin_slug": skill.builtin_slug,
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
