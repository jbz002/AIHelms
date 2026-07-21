"""documents 表的数据库操作。"""

import hashlib

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
    chunk_count: int | None = None,
    error_message: str = "",
) -> None:
    values: dict = {"ingest_status": status}
    if chunk_count is not None:
        values["chunk_count"] = chunk_count
    if error_message:
        values["error_message"] = error_message
    await session.execute(
        update(Document).where(Document.id == document_id).values(**values)
    )
    await session.flush()


async def upsert_by_source(
    session: AsyncSession,
    source_type: str,
    source_id: int,
    *,
    title: str,
    content: str,
    library: str,
    version: str,
    created_by: int | None,
    chunk_count: int = 0,
    metadata_: dict,
    reset_to_pending_on_content_change: bool = True,
) -> Document:
    """幂等 upsert：按 (source_type, source_id) 维护 Document。

    不存在则创建（ingest_status='pending'）；存在则更新 title/content/
    chunk_count/metadata/content_hash，并在内容变化且当前为 'ingested' 时
    回退为 'pending'（镜像 document_service.update_document 语义，支持
    重新入库）。返回持久化后的 Document。
    """
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    existing = await find_by_source(session, source_type, source_id)
    if existing is None:
        doc = Document(
            title=title,
            content=content,
            library=library,
            version=version,
            source_type=source_type,
            source_id=source_id,
            chunk_count=chunk_count,
            ingest_status="pending",
            content_hash=content_hash,
            created_by=created_by,
            metadata_=metadata_,
        )
        session.add(doc)
        await session.flush()
        await session.refresh(doc)
        return doc

    content_changed = existing.content_hash != content_hash
    existing.title = title
    existing.content = content
    existing.chunk_count = chunk_count
    existing.metadata_ = metadata_
    existing.content_hash = content_hash
    if (
        reset_to_pending_on_content_change
        and content_changed
        and existing.ingest_status == "ingested"
    ):
        existing.ingest_status = "pending"
        existing.error_message = ""
    await session.flush()
    await session.refresh(existing)
    return existing


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
    version: str | None = None,
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
    if version:
        normalized = "" if version.lower() == "latest" else version
        stmt = stmt.where(Document.version == normalized)
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
    version: str | None = None,
) -> int:
    stmt = select(func.count())
    if library:
        stmt = stmt.where(func.lower(Document.library) == library.lower())
    if source_type:
        stmt = stmt.where(Document.source_type == source_type)
    if ingest_status:
        stmt = stmt.where(Document.ingest_status == ingest_status)
    if version:
        normalized = "" if version.lower() == "latest" else version
        stmt = stmt.where(Document.version == normalized)
    result = await session.execute(stmt)
    return result.scalar_one()


async def count_grouped_by_status(
    session: AsyncSession,
    library: str | None = None,
    version: str | None = None,
) -> list[dict]:
    stmt = select(
        Document.ingest_status,
        func.count().label("count"),
        func.coalesce(func.sum(Document.chunk_count), 0).label("total_chunks"),
    ).group_by(Document.ingest_status)
    if library:
        stmt = stmt.where(func.lower(Document.library) == library.lower())
    if version:
        normalized = "" if version.lower() == "latest" else version
        stmt = stmt.where(Document.version == normalized)
    result = await session.execute(stmt)
    return [
        {
            "ingest_status": row.ingest_status,
            "count": row.count,
            "total_chunks": row.total_chunks,
        }
        for row in result.all()
    ]


async def count_grouped_by_library_source_status(
    session: AsyncSession,
) -> list[dict]:
    """按 library + source_type + ingest_status 三维分组计数。

    供 /documents/dashboard-summary 聚合：一次查询同时算出全局 by_source/
    by_status/total_documents 以及按 library 细分的同维度指标。library 用
    func.lower 归一化，避免与 docs-mcp 库名大小写漂移导致前端漏匹配。
    """
    stmt = select(
        func.lower(Document.library).label("library"),
        Document.source_type,
        Document.ingest_status,
        func.count().label("count"),
    ).group_by(
        func.lower(Document.library),
        Document.source_type,
        Document.ingest_status,
    )
    result = await session.execute(stmt)
    return [
        {
            "library": row.library,
            "source_type": row.source_type,
            "ingest_status": row.ingest_status,
            "count": row.count,
        }
        for row in result.all()
    ]


async def list_by_ingest_status(
    session: AsyncSession,
    statuses: list[str],
    library: str | None = None,
    source_type: str | None = None,
) -> list[Document]:
    stmt = select(Document).where(Document.ingest_status.in_(statuses))
    if library:
        stmt = stmt.where(func.lower(Document.library) == library.lower())
    if source_type:
        stmt = stmt.where(Document.source_type == source_type)
    stmt = stmt.order_by(Document.id.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_content_hash(
    session: AsyncSession,
    document_id: int,
    content_hash: str,
) -> None:
    await session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(content_hash=content_hash)
    )
    await session.flush()


async def delete_document(session: AsyncSession, document_id: int) -> None:
    await session.execute(delete(Document).where(Document.id == document_id))
    await session.flush()


async def delete_by_library_version(
    session: AsyncSession,
    library: str,
    version: str,
) -> int:
    """按 library + version 批量删除文档，返回删除行数。"""
    stmt = delete(Document).where(
        func.lower(Document.library) == library.lower(),
        Document.version == version,
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.rowcount


async def delete_by_library(session: AsyncSession, library: str) -> int:
    """按 library 批量删除所有文档，返回删除行数。用于删除整个文档库。"""
    stmt = delete(Document).where(func.lower(Document.library) == library.lower())
    result = await session.execute(stmt)
    await session.flush()
    return result.rowcount
