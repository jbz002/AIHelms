"""文档知识库注册服务：确保知识库在平台 DB 中有记录。"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from models.db import DocumentLibrary
from repositories import document_library_repo, document_repo

logger = logging.getLogger(__name__)


async def ensure_library_exists(
    session: AsyncSession,
    name: str,
    created_by: int | None = None,
    source_url: str = "",
) -> DocumentLibrary:
    """确保知识库在 document_libraries 表中存在，不存在则创建。返回记录。"""
    library = await document_library_repo.find_by_name(session, name)
    if library is not None:
        if source_url and not library.source_url:
            await document_library_repo.update_source_url(
                session, library.id, source_url
            )
        return library

    library = DocumentLibrary(
        name=name,
        source_url=source_url,
        created_by=created_by,
    )
    return await document_library_repo.create(session, library)


async def refresh_document_counts(
    session: AsyncSession, library_name: str
) -> None:
    """从 documents 表重新计算文档计数，写回 document_libraries。"""
    library = await document_library_repo.find_by_name(session, library_name)
    if library is None:
        return
    count = await document_repo.count_by_library(session, library_name)
    await document_library_repo.update_document_count(session, library.id, count)


async def list_libraries(session: AsyncSession) -> list[dict]:
    """获取所有知识库列表，返回序列化字典。"""
    libraries = await document_library_repo.list_all(session)
    return [
        {
            "id": lib.id,
            "name": lib.name,
            "description": lib.description,
            "document_count": lib.document_count,
            "total_chunks": lib.total_chunks,
            "source_url": lib.source_url,
            "created_by": lib.created_by,
            "created_at": lib.created_at.isoformat() if lib.created_at else None,
            "updated_at": lib.updated_at.isoformat() if lib.updated_at else None,
        }
        for lib in libraries
    ]
