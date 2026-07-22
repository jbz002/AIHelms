"""S4 · 治理 Label 仓库（label_definitions + skill_labels）。"""

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import LabelDefinition, SkillLabel

# ─── label_definitions CRUD ─────────────────────────────────────────


async def list_definitions(
    session: AsyncSession, active_only: bool = True
) -> list[LabelDefinition]:
    stmt = select(LabelDefinition)
    if active_only:
        stmt = stmt.where(LabelDefinition.is_active == True)  # noqa: E712
    stmt = stmt.order_by(LabelDefinition.sort_order, LabelDefinition.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_definition_by_id(
    session: AsyncSession, definition_id: int
) -> LabelDefinition | None:
    result = await session.execute(
        select(LabelDefinition).where(LabelDefinition.id == definition_id)
    )
    return result.scalar_one_or_none()


async def find_definition_by_name(
    session: AsyncSession, name: str
) -> LabelDefinition | None:
    result = await session.execute(
        select(LabelDefinition).where(LabelDefinition.name == name)
    )
    return result.scalar_one_or_none()


async def find_skill_ids_by_label_name(
    session: AsyncSession, name: str
) -> list[int]:
    """按 label name 解析其关联的所有 skill_id（CLI 搜索 label 过滤用）。"""
    result = await session.execute(
        select(SkillLabel.skill_id)
        .join(LabelDefinition, LabelDefinition.id == SkillLabel.label_id)
        .where(LabelDefinition.name == name)
    )
    return [row[0] for row in result.all()]


async def create_definition(
    session: AsyncSession, definition: LabelDefinition
) -> LabelDefinition:
    session.add(definition)
    await session.flush()
    await session.refresh(definition)
    return definition


async def update_definition(
    session: AsyncSession,
    definition: LabelDefinition,
    *,
    display_name_key: str | None = None,
    color: str | None = None,
    sort_order: int | None = None,
    is_active: bool | None = None,
) -> LabelDefinition:
    values: dict = {}
    if display_name_key is not None:
        values["display_name_key"] = display_name_key
    if color is not None:
        values["color"] = color
    if sort_order is not None:
        values["sort_order"] = sort_order
    if is_active is not None:
        values["is_active"] = is_active
    if values:
        await session.execute(
            update(LabelDefinition)
            .where(LabelDefinition.id == definition.id)
            .values(**values)
        )
        await session.refresh(definition)
    return definition


# ─── skill_labels 关联 ──────────────────────────────────────────────


async def grant(
    session: AsyncSession,
    skill_id: int,
    label_id: int,
    granted_by: int | None,
    note: str = "",
) -> SkillLabel | None:
    """授予标签；已持有则 ON CONFLICT DO NOTHING 返回 None（幂等）。"""
    stmt = (
        pg_insert(SkillLabel)
        .values(
            skill_id=skill_id,
            label_id=label_id,
            granted_by=granted_by,
            note=note,
        )
        .on_conflict_do_nothing(constraint="uq_skill_labels_skill_label")
        .returning(SkillLabel)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def revoke(session: AsyncSession, skill_id: int, label_id: int) -> int:
    result = await session.execute(
        sa_delete(SkillLabel).where(
            SkillLabel.skill_id == skill_id,
            SkillLabel.label_id == label_id,
        )
    )
    return result.rowcount


def _enrich(row: SkillLabel, definition: LabelDefinition) -> dict:
    return {
        "id": row.id,
        "label_id": definition.id,
        "name": definition.name,
        "display_name_key": definition.display_name_key,
        "color": definition.color,
        "sort_order": definition.sort_order,
        "granted_by": row.granted_by,
        "granted_at": row.granted_at.isoformat() if row.granted_at else None,
        "note": row.note or "",
    }


async def list_by_skill(session: AsyncSession, skill_id: int) -> list[dict]:
    stmt = (
        select(SkillLabel, LabelDefinition)
        .join(LabelDefinition, LabelDefinition.id == SkillLabel.label_id)
        .where(SkillLabel.skill_id == skill_id)
        .order_by(LabelDefinition.sort_order, SkillLabel.id)
    )
    result = await session.execute(stmt)
    return [_enrich(row, definition) for row, definition in result.all()]


async def map_by_skills(
    session: AsyncSession, skill_ids: list[int]
) -> dict[int, list[dict]]:
    """批量加载多 skill 的标签（列表场景避免 N+1）。"""
    if not skill_ids:
        return {}
    stmt = (
        select(SkillLabel, LabelDefinition)
        .join(LabelDefinition, LabelDefinition.id == SkillLabel.label_id)
        .where(SkillLabel.skill_id.in_(skill_ids))
        .order_by(LabelDefinition.sort_order, SkillLabel.id)
    )
    result = await session.execute(stmt)
    mapping: dict[int, list[dict]] = {sid: [] for sid in skill_ids}
    for row, definition in result.all():
        mapping.setdefault(row.skill_id, []).append(_enrich(row, definition))
    return mapping
