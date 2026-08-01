"""document_libraries 表的数据库操作。"""

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import DocumentLibrary


async def create(session: AsyncSession, library: DocumentLibrary) -> DocumentLibrary:
    session.add(library)
    await session.flush()
    await session.refresh(library)
    return library


async def find_by_name(session: AsyncSession, name: str) -> DocumentLibrary | None:
    result = await session.execute(
        select(DocumentLibrary).where(func.lower(DocumentLibrary.name) == name.lower())
    )
    return result.scalar_one_or_none()


async def find_by_id(session: AsyncSession, library_id: int) -> DocumentLibrary | None:
    result = await session.execute(
        select(DocumentLibrary).where(DocumentLibrary.id == library_id)
    )
    return result.scalar_one_or_none()


async def list_all(session: AsyncSession) -> list[DocumentLibrary]:
    stmt = select(DocumentLibrary).order_by(DocumentLibrary.id.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_document_count(
    session: AsyncSession, library_id: int, document_count: int
) -> None:
    await session.execute(
        update(DocumentLibrary)
        .where(DocumentLibrary.id == library_id)
        .values(document_count=document_count)
    )
    await session.flush()


async def update_counts(
    session: AsyncSession,
    library_id: int,
    document_count: int,
    total_chunks: int,
) -> None:
    """同时刷新库的文档数与分块总数（两者同源同刷，避免 total_chunks 漂移）。"""
    await session.execute(
        update(DocumentLibrary)
        .where(DocumentLibrary.id == library_id)
        .values(document_count=document_count, total_chunks=total_chunks)
    )
    await session.flush()


async def update_source_url(
    session: AsyncSession, library_id: int, source_url: str
) -> None:
    await session.execute(
        update(DocumentLibrary)
        .where(DocumentLibrary.id == library_id)
        .values(source_url=source_url)
    )
    await session.flush()


async def update_active_version(
    session: AsyncSession, library_id: int, active_version: str
) -> None:
    """设置文档库生效版本（平台侧生效指针，docs-mcp 不感知）。"""
    await session.execute(
        update(DocumentLibrary)
        .where(DocumentLibrary.id == library_id)
        .values(active_version=active_version)
    )
    await session.flush()


async def update_library_info(
    session: AsyncSession,
    library_id: int,
    name: str | None = None,
    description: str | None = None,
) -> None:
    values = {}
    if name is not None:
        values["name"] = name
    if description is not None:
        values["description"] = description
    if not values:
        return
    await session.execute(
        update(DocumentLibrary).where(DocumentLibrary.id == library_id).values(**values)
    )
    await session.flush()


async def search(
    session: AsyncSession,
    keyword: str,
    page: int = 1,
    page_size: int = 20,
) -> list[DocumentLibrary]:
    stmt = (
        select(DocumentLibrary)
        .where(DocumentLibrary.name.ilike(f"%{keyword}%"))
        .order_by(DocumentLibrary.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_search(session: AsyncSession, keyword: str) -> int:
    stmt = select(func.count()).where(DocumentLibrary.name.ilike(f"%{keyword}%"))
    result = await session.execute(stmt)
    return result.scalar_one()


async def delete_library(session: AsyncSession, library_id: int) -> None:
    await session.execute(
        delete(DocumentLibrary).where(DocumentLibrary.id == library_id)
    )
    await session.flush()
