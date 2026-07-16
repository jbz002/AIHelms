"""documents 表的数据库操作。"""

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Document


async def create(session: AsyncSession, document: Document) -> Document:
    session.add(document)
    await session.flush()
    await session.refresh(document)
    return document


async def find_by_id(session: AsyncSession, document_id: int) -> Document | None:
    result = await session.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


async def find_by_source(
    session: AsyncSession, source_type: str, source_id: int
) -> Document | None:
    result = await session.execute(
        select(Document).where(
            Document.source_type == source_type,
            Document.source_id == source_id,
        )
    )
    return result.scalar_one_or_none()


async def list_by_library(
    session: AsyncSession,
    library: str,
    page: int = 1,
    page_size: int = 20,
) -> list[Document]:
    stmt = (
        select(Document)
        .where(func.lower(Document.library) == library.lower())
        .order_by(Document.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_by_library(session: AsyncSession, library: str) -> int:
    stmt = select(func.count()).where(func.lower(Document.library) == library.lower())
    result = await session.execute(stmt)
    return result.scalar_one()


async def update_ingest_status(
    session: AsyncSession,
    document_id: int,
    status: str,
    chunk_count: int = 0,
    error_message: str = "",
) -> None:
    values: dict = {"ingest_status": status, "chunk_count": chunk_count}
    if error_message:
        values["error_message"] = error_message
    await session.execute(
        update(Document).where(Document.id == document_id).values(**values)
    )
    await session.flush()


async def update_document_fields(
    session: AsyncSession,
    document_id: int,
    title: str | None = None,
    content: str | None = None,
    metadata_: dict | None = None,
) -> None:
    values = {}
    if title is not None:
        values["title"] = title
    if content is not None:
        values["content"] = content
    if metadata_ is not None:
        values["metadata_"] = metadata_
    if not values:
        return
    await session.execute(
        update(Document).where(Document.id == document_id).values(**values)
    )
    await session.flush()


async def list_all(
    session: AsyncSession,
    library: str | None = None,
    source_type: str | None = None,
    ingest_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> list[Document]:
    stmt = select(Document)
    if library:
        stmt = stmt.where(func.lower(Document.library) == library.lower())
    if source_type:
        stmt = stmt.where(Document.source_type == source_type)
    if ingest_status:
        stmt = stmt.where(Document.ingest_status == ingest_status)
    stmt = (
        stmt.order_by(Document.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_all(
    session: AsyncSession,
    library: str | None = None,
    source_type: str | None = None,
    ingest_status: str | None = None,
) -> int:
    stmt = select(func.count())
    if library:
        stmt = stmt.where(func.lower(Document.library) == library.lower())
    if source_type:
        stmt = stmt.where(Document.source_type == source_type)
    if ingest_status:
        stmt = stmt.where(Document.ingest_status == ingest_status)
    result = await session.execute(stmt)
    return result.scalar_one()


async def delete_document(session: AsyncSession, document_id: int) -> None:
    await session.execute(delete(Document).where(Document.id == document_id))
    await session.flush()
