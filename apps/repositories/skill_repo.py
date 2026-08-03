from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Skill, SkillCategory
from services.visibility_service import list_visibility_clause

# ─── Skill ───────────────────────────────────────────────────────────────────


async def create(session: AsyncSession, skill: Skill) -> Skill:
    session.add(skill)
    await session.flush()
    await session.refresh(skill)
    return skill


async def find_by_id(session: AsyncSession, skill_id: int) -> Skill | None:
    result = await session.execute(select(Skill).where(Skill.id == skill_id))
    return result.scalar_one_or_none()


async def find_by_skill_id(session: AsyncSession, skill_id: str) -> Skill | None:
    result = await session.execute(select(Skill).where(Skill.skill_id == skill_id))
    return result.scalar_one_or_none()


async def find_by_name(session: AsyncSession, name: str) -> Skill | None:
    result = await session.execute(select(Skill).where(Skill.name == name))
    return result.scalar_one_or_none()


async def find_all(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    category: str | None = None,
    is_published: bool | None = None,
    is_active: bool | None = None,
    viewer_id: int | None = None,
    is_admin: bool = False,
) -> list[Skill]:
    stmt = select(Skill).order_by(Skill.id.desc())
    if category:
        stmt = stmt.where(Skill.category == category)
    if is_published is not None:
        stmt = stmt.where(Skill.is_published == is_published)
    if is_active is not None:
        stmt = stmt.where(Skill.is_active == is_active)
    vis_clause = list_visibility_clause(Skill, viewer_id, is_admin)
    if vis_clause is not None:
        stmt = stmt.where(vis_clause)
    # S3 · 治理下架 overlay：非 admin（含匿名）不见 hidden Skill
    if not is_admin:
        stmt = stmt.where(Skill.hidden == False)  # noqa: E712
    offset = (page - 1) * page_size
    stmt = stmt.limit(page_size).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_all(
    session: AsyncSession,
    category: str | None = None,
    is_published: bool | None = None,
    is_active: bool | None = None,
    viewer_id: int | None = None,
    is_admin: bool = False,
) -> int:
    stmt = select(func.count(Skill.id))
    if category:
        stmt = stmt.where(Skill.category == category)
    if is_published is not None:
        stmt = stmt.where(Skill.is_published == is_published)
    if is_active is not None:
        stmt = stmt.where(Skill.is_active == is_active)
    vis_clause = list_visibility_clause(Skill, viewer_id, is_admin)
    if vis_clause is not None:
        stmt = stmt.where(vis_clause)
    # S3 · 治理下架 overlay：非 admin（含匿名）不见 hidden Skill
    if not is_admin:
        stmt = stmt.where(Skill.hidden == False)  # noqa: E712
    result = await session.execute(stmt)
    return result.scalar_one()


async def find_all_by_creator(
    session: AsyncSession,
    creator_id: int,
    page: int = 1,
    page_size: int = 50,
) -> list[Skill]:
    """contributor 工作台：列出某用户创建的全部 Skill（含草稿/隐藏/未发布）。"""
    offset = (page - 1) * page_size
    stmt = (
        select(Skill)
        .where(Skill.created_by == creator_id)
        .order_by(Skill.id.desc())
        .limit(page_size)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_by_creator(session: AsyncSession, creator_id: int) -> int:
    """contributor 工作台：统计某用户创建的 Skill 总数。"""
    stmt = select(func.count(Skill.id)).where(Skill.created_by == creator_id)
    result = await session.execute(stmt)
    return result.scalar_one()


async def find_by_ids(session: AsyncSession, ids: list[int]) -> list[Skill]:
    if not ids:
        return []
    result = await session.execute(select(Skill).where(Skill.id.in_(ids)))
    return list(result.scalars().all())


async def delete(session: AsyncSession, skill_id: int) -> bool:
    result = await session.execute(sa_delete(Skill).where(Skill.id == skill_id))
    return result.rowcount > 0


async def increment_install_count(session: AsyncSession, skill_id: int) -> None:
    skill = await find_by_id(session, skill_id)
    if skill:
        skill.install_count = (skill.install_count or 0) + 1


# ─── CLI 分发通道搜索（S7 阶段一）──────────────────────────────────────────────


def _cli_search_stmt(
    q: str | None,
    category: str | None,
    sort: str,
) -> select:
    """CLI 搜索 Select：published-only + 非 hidden + 可选关键词/类目过滤。"""
    stmt = select(Skill).where(
        Skill.is_published == True,  # noqa: E712
        Skill.hidden == False,  # noqa: E712
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            (Skill.name.ilike(pattern)) | (Skill.description.ilike(pattern))
        )
    if category:
        stmt = stmt.where(Skill.category == category)
    if sort == "install_count":
        stmt = stmt.order_by(Skill.install_count.desc().nulls_last(), Skill.id.desc())
    elif sort == "name":
        stmt = stmt.order_by(Skill.name.asc())
    else:
        stmt = stmt.order_by(Skill.id.desc())
    return stmt


async def cli_search_skills(
    session: AsyncSession,
    *,
    q: str | None = None,
    category: str | None = None,
    sort: str = "newest",
    page: int = 1,
    page_size: int = 50,
) -> list[Skill]:
    stmt = _cli_search_stmt(q, category, sort)
    offset = (page - 1) * page_size
    stmt = stmt.limit(page_size).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def cli_count_skills(
    session: AsyncSession,
    *,
    q: str | None = None,
    category: str | None = None,
    sort: str = "newest",
) -> int:
    from sqlalchemy import func as sa_func

    base = _cli_search_stmt(q, category, sort)
    stmt = select(sa_func.count()).select_from(base.subquery())
    result = await session.execute(stmt)
    return result.scalar_one()


# ─── SkillCategory ──────────────────────────────────────────────────────────


async def list_categories(session: AsyncSession) -> list[SkillCategory]:
    result = await session.execute(
        select(SkillCategory).order_by(SkillCategory.sort_order, SkillCategory.id)
    )
    return list(result.scalars().all())


async def find_category_by_id(
    session: AsyncSession, category_id: int
) -> SkillCategory | None:
    result = await session.execute(
        select(SkillCategory).where(SkillCategory.id == category_id)
    )
    return result.scalar_one_or_none()


async def find_category_by_name(
    session: AsyncSession, name: str
) -> SkillCategory | None:
    result = await session.execute(
        select(SkillCategory).where(SkillCategory.name == name)
    )
    return result.scalar_one_or_none()


async def create_category(
    session: AsyncSession, category: SkillCategory
) -> SkillCategory:
    session.add(category)
    await session.flush()
    await session.refresh(category)
    return category


async def delete_category(session: AsyncSession, category_id: int) -> bool:
    result = await session.execute(
        sa_delete(SkillCategory).where(SkillCategory.id == category_id)
    )
    return result.rowcount > 0
