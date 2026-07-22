"""S4 · Skill 版本别名 Tag 仓库。

latest 为系统保留只读 tag，由 skill_tag_service.refresh_latest_tag 维护。
用户 tag（beta/stable）经 upsert 创建或移动到新 version_id。
"""

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import SkillTag


async def upsert(
    session: AsyncSession,
    skill_id: int,
    tag_name: str,
    version_id: int,
    is_system: bool = False,
) -> SkillTag:
    """存在则移动 version_id（含 is_system），不存在则创建。ON CONFLICT 原子。"""
    stmt = (
        pg_insert(SkillTag)
        .values(
            skill_id=skill_id,
            tag_name=tag_name,
            version_id=version_id,
            is_system=is_system,
        )
        .on_conflict_do_update(
            constraint="uq_skill_tags_skill_tag",
            set_={"version_id": version_id, "is_system": is_system},
        )
        .returning(SkillTag)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def find_by_skill(session: AsyncSession, skill_id: int) -> list[SkillTag]:
    result = await session.execute(
        select(SkillTag)
        .where(SkillTag.skill_id == skill_id)
        .order_by(SkillTag.created_at)
    )
    return list(result.scalars().all())


async def find_by_skill_and_name(
    session: AsyncSession, skill_id: int, tag_name: str
) -> SkillTag | None:
    result = await session.execute(
        select(SkillTag).where(
            SkillTag.skill_id == skill_id,
            SkillTag.tag_name == tag_name,
        )
    )
    return result.scalar_one_or_none()


async def find_system_latest(session: AsyncSession, skill_id: int) -> SkillTag | None:
    result = await session.execute(
        select(SkillTag).where(
            SkillTag.skill_id == skill_id,
            SkillTag.tag_name == "latest",
            SkillTag.is_system == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def delete_by_skill_and_name(
    session: AsyncSession, skill_id: int, tag_name: str
) -> int:
    result = await session.execute(
        sa_delete(SkillTag).where(
            SkillTag.skill_id == skill_id,
            SkillTag.tag_name == tag_name,
        )
    )
    return result.rowcount


async def delete_system_latest(session: AsyncSession, skill_id: int) -> None:
    """无 published 版本时清除 latest 系统指针。"""
    await session.execute(
        sa_delete(SkillTag).where(
            SkillTag.skill_id == skill_id,
            SkillTag.tag_name == "latest",
            SkillTag.is_system == True,  # noqa: E712
        )
    )
