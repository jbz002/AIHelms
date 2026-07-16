"""文档查询/更新/删除服务。文档创建由 upload/crawl 流程自动完成。"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from models.db import Document
from repositories import document_repo

logger = logging.getLogger(__name__)


def _serialize_document(doc: Document) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "content": doc.content[:500] if doc.content else "",
        "library": doc.library,
        "version": doc.version,
        "source_type": doc.source_type,
        "source_id": doc.source_id,
        "chunk_count": doc.chunk_count,
        "ingest_status": doc.ingest_status,
        "content_hash": doc.content_hash,
        "error_message": doc.error_message,
        "created_by": doc.created_by,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        "metadata": doc.metadata_ if doc.metadata_ else {},
    }


async def get_document_by_id(session: AsyncSession, document_id: int) -> dict:
    """根据 ID 获取文档详情。"""
    doc = await document_repo.find_by_id(session, document_id)
    if doc is None:
        raise NotFoundError("document", document_id)
    result = _serialize_document(doc)
    result["content"] = doc.content or ""
    return result


async def list_documents(
    session: AsyncSession,
    library: str | None = None,
    source_type: str | None = None,
    ingest_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询文档列表，支持多条件过滤和分页。"""
    total = await document_repo.count_all(session, library, source_type, ingest_status)
    docs = await document_repo.list_all(
        session, library, source_type, ingest_status, page, page_size
    )
    return {
        "items": [_serialize_document(d) for d in docs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def update_document(
    session: AsyncSession,
    document_id: int,
    title: str | None = None,
    content: str | None = None,
    metadata_: dict | None = None,
) -> dict:
    """更新文档标题/内容/元数据。"""
    doc = await document_repo.find_by_id(session, document_id)
    if doc is None:
        raise NotFoundError("document", document_id)
    await document_repo.update_document_fields(
        session, document_id, title=title, content=content, metadata_=metadata_
    )
    await session.commit()
    await session.refresh(doc)
    return _serialize_document(doc)


async def delete_document(session: AsyncSession, document_id: int) -> None:
    """删除文档。"""
    doc = await document_repo.find_by_id(session, document_id)
    if doc is None:
        raise NotFoundError("document", document_id)
    await document_repo.delete_document(session, document_id)
    await session.commit()
