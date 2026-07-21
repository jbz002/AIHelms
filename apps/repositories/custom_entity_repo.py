"""
自定义实体 Repository 层
"""
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import CustomEntity, CustomEntityType
from services.visibility_service import list_visibility_clause

# ─── Type CRUD ─────────────────────────────────────────────────────────────


async def create_type(session: AsyncSession, type_def: CustomEntityType) -> CustomEntityType:
    """创建自定义实体类型"""
    session.add(type_def)
    await session.flush()
    await session.refresh(type_def)
    return type_def


async def find_type_by_key(session: AsyncSession, type_key: str) -> CustomEntityType | None:
    """根据 type_key 查找类型"""
    result = await session.execute(
        select(CustomEntityType).where(CustomEntityType.type_key == type_key)
    )
    return result.scalar_one_or_none()


async def find_type_by_id(session: AsyncSession, type_id: int) -> CustomEntityType | None:
    """根据 ID 查找类型"""
    result = await session.execute(
        select(CustomEntityType).where(CustomEntityType.id == type_id)
    )
    return result.scalar_one_or_none()


async def list_types(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    is_active: bool | None = None,
    is_published: bool | None = None,
) -> list[CustomEntityType]:
    """获取类型列表"""
    stmt = select(CustomEntityType).order_by(CustomEntityType.id)
    if is_active is not None:
        stmt = stmt.where(CustomEntityType.is_active == is_active)
    if is_published is not None:
        stmt = stmt.where(CustomEntityType.is_published == is_published)

    offset = (page - 1) * page_size
    stmt = stmt.limit(page_size).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_types(
    session: AsyncSession,
    is_active: bool | None = None,
    is_published: bool | None = None,
) -> int:
    """统计类型数量"""
    stmt = select(func.count(CustomEntityType.id))
    if is_active is not None:
        stmt = stmt.where(CustomEntityType.is_active == is_active)
    if is_published is not None:
        stmt = stmt.where(CustomEntityType.is_published == is_published)
    result = await session.execute(stmt)
    return result.scalar_one()


async def update_type(session: AsyncSession, type_def: CustomEntityType) -> CustomEntityType:
    """更新类型"""
    await session.flush()
    await session.refresh(type_def)
    return type_def


async def delete_type(session: AsyncSession, type_id: int) -> bool:
    """删除类型"""
    result = await session.execute(
        sa_delete(CustomEntityType).where(CustomEntityType.id == type_id)
    )
    return result.rowcount > 0


# ─── Entity CRUD ───────────────────────────────────────────────────────────


async def create_entity(session: AsyncSession, entity: CustomEntity) -> CustomEntity:
    """创建自定义实体实例"""
    session.add(entity)
    await session.flush()
    await session.refresh(entity)
    return entity


async def find_entity_by_id(session: AsyncSession, entity_id: int) -> CustomEntity | None:
    """根据 ID 查找实例"""
    result = await session.execute(
        select(CustomEntity).where(CustomEntity.id == entity_id)
    )
    return result.scalar_one_or_none()


async def list_entities(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    type_key: str | None = None,
    is_published: bool | None = None,
    is_active: bool | None = None,
    viewer_id: int | None = None,
    is_admin: bool = False,
) -> list[CustomEntity]:
    """获取实例列表"""
    stmt = select(CustomEntity).order_by(CustomEntity.id.desc())

    if type_key:
        stmt = stmt.where(CustomEntity.type_key == type_key)
    if is_published is not None:
        stmt = stmt.where(CustomEntity.is_published == is_published)
    if is_active is not None:
        stmt = stmt.where(CustomEntity.is_active == is_active)
    vis_clause = list_visibility_clause(CustomEntity, viewer_id, is_admin)
    if vis_clause is not None:
        stmt = stmt.where(vis_clause)

    offset = (page - 1) * page_size
    stmt = stmt.limit(page_size).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_entities(
    session: AsyncSession,
    type_key: str | None = None,
    is_published: bool | None = None,
    is_active: bool | None = None,
    viewer_id: int | None = None,
    is_admin: bool = False,
) -> int:
    """统计实例数量"""
    stmt = select(func.count(CustomEntity.id))

    if type_key:
        stmt = stmt.where(CustomEntity.type_key == type_key)
    if is_published is not None:
        stmt = stmt.where(CustomEntity.is_published == is_published)
    if is_active is not None:
        stmt = stmt.where(CustomEntity.is_active == is_active)
    vis_clause = list_visibility_clause(CustomEntity, viewer_id, is_admin)
    if vis_clause is not None:
        stmt = stmt.where(vis_clause)

    result = await session.execute(stmt)
    return result.scalar_one()


async def update_entity(session: AsyncSession, entity: CustomEntity) -> CustomEntity:
    """更新实例"""
    await session.flush()
    await session.refresh(entity)
    return entity


async def delete_entity(session: AsyncSession, entity_id: int) -> bool:
    """删除实例"""
    result = await session.execute(
        sa_delete(CustomEntity).where(CustomEntity.id == entity_id)
    )
    return result.rowcount > 0


async def count_entities_by_type(session: AsyncSession, type_id: int) -> int:
    """统计某类型的实例数量（用于兼容性检查）"""
    stmt = select(func.count(CustomEntity.id)).where(CustomEntity.type_id == type_id)
    result = await session.execute(stmt)
    return result.scalar_one()
