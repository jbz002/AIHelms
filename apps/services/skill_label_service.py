"""S4 · 治理 Label 服务（label_definitions CRUD + skill_labels 授予/撤销）。

Label 是显式治理标注位（recommended/official/verified），不进质量分。
权限在 router 层用 require_permission('skill:label:manage') 把关。
"""

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import LabelDefinition
from repositories import skill_label_repo, skill_repo

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")
_COLOR_RE = re.compile(r"^[a-z0-9]{0,16}$")


def _serialize_definition(d: LabelDefinition) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "display_name_key": d.display_name_key,
        "color": d.color,
        "sort_order": d.sort_order,
        "is_active": d.is_active,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


# ─── label_definitions CRUD ─────────────────────────────────────────


async def list_definitions(
    session: AsyncSession, active_only: bool = True
) -> list[dict]:
    defs = await skill_label_repo.list_definitions(session, active_only=active_only)
    return [_serialize_definition(d) for d in defs]


async def create_definition(
    session: AsyncSession,
    name: str,
    display_name_key: str,
    color: str = "",
    sort_order: int = 0,
    is_active: bool = True,
) -> dict:
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        raise ValidationError("标签定义 name 仅支持小写字母、数字、下划线，长度 1-32")
    if not display_name_key or len(display_name_key) > 64:
        raise ValidationError("display_name_key 必填且长度 ≤ 64")
    if not _COLOR_RE.match(color):
        raise ValidationError("color 仅支持小写字母数字，长度 ≤ 16")
    if await skill_label_repo.find_definition_by_name(session, name):
        raise ConflictError(f"标签定义 '{name}' 已存在")
    definition = LabelDefinition(
        name=name,
        display_name_key=display_name_key,
        color=color,
        sort_order=sort_order,
        is_active=is_active,
    )
    definition = await skill_label_repo.create_definition(session, definition)
    await session.commit()
    logger.info("label definition created", extra={"name": name})
    return _serialize_definition(definition)


async def update_definition(
    session: AsyncSession,
    definition_id: int,
    *,
    display_name_key: str | None = None,
    color: str | None = None,
    sort_order: int | None = None,
    is_active: bool | None = None,
) -> dict:
    definition = await skill_label_repo.find_definition_by_id(session, definition_id)
    if not definition:
        raise NotFoundError("label_definition", definition_id)
    if display_name_key is not None and (
        not display_name_key or len(display_name_key) > 64
    ):
        raise ValidationError("display_name_key 必填且长度 ≤ 64")
    if color is not None and not _COLOR_RE.match(color):
        raise ValidationError("color 仅支持小写字母数字，长度 ≤ 16")
    definition = await skill_label_repo.update_definition(
        session,
        definition,
        display_name_key=display_name_key,
        color=color,
        sort_order=sort_order,
        is_active=is_active,
    )
    await session.commit()
    return _serialize_definition(definition)


async def deactivate_definition(session: AsyncSession, definition_id: int) -> None:
    """停用标签定义（软删除，保留已授予记录的引用完整性）。"""
    definition = await skill_label_repo.find_definition_by_id(session, definition_id)
    if not definition:
        raise NotFoundError("label_definition", definition_id)
    await skill_label_repo.update_definition(session, definition, is_active=False)
    await session.commit()


# ─── skill_labels 授予/撤销 ─────────────────────────────────────────


async def list_labels(session: AsyncSession, skill_id: int) -> list[dict]:
    await _require_skill(session, skill_id)
    return await skill_label_repo.list_by_skill(session, skill_id)


async def grant_label(
    session: AsyncSession,
    skill_id: int,
    label_name: str,
    granted_by: int | None,
    note: str = "",
) -> dict:
    await _require_skill(session, skill_id)
    definition = await skill_label_repo.find_definition_by_name(session, label_name)
    if not definition or not definition.is_active:
        raise NotFoundError("label_definition", label_name)
    granted = await skill_label_repo.grant(
        session, skill_id, definition.id, granted_by, note
    )
    if granted is None:
        raise ConflictError("该 Skill 已持有此标签")
    await session.commit()
    logger.info(
        "skill label granted",
        extra={"skill_id": skill_id, "label": label_name, "by": granted_by},
    )
    return {
        "id": granted.id,
        "label_id": definition.id,
        "name": definition.name,
        "display_name_key": definition.display_name_key,
        "color": definition.color,
        "sort_order": definition.sort_order,
        "granted_by": granted.granted_by,
        "granted_at": granted.granted_at.isoformat() if granted.granted_at else None,
        "note": granted.note or "",
    }


async def revoke_label(session: AsyncSession, skill_id: int, label_name: str) -> None:
    await _require_skill(session, skill_id)
    definition = await skill_label_repo.find_definition_by_name(session, label_name)
    if not definition:
        raise NotFoundError("label_definition", label_name)
    rowcount = await skill_label_repo.revoke(session, skill_id, definition.id)
    if rowcount == 0:
        raise NotFoundError("skill_label", label_name)
    await session.commit()
    logger.info(
        "skill label revoked", extra={"skill_id": skill_id, "label": label_name}
    )


async def _require_skill(session: AsyncSession, skill_id: int) -> None:
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
