"""document_libraries 表的数据库操作。"""

from sqlalchemy import func, select, update
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


async def update_source_url(
    session: AsyncSession, library_id: int, source_url: str
) -> None:
    await session.execute(
        update(DocumentLibrary)
        .where(DocumentLibrary.id == library_id)
        .values(source_url=source_url)
    )
    await session.flush()
