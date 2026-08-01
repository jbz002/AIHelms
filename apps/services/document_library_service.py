"""文档知识库注册服务：确保知识库在平台 DB 中有记录。"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, NotFoundError
from models.db import DocumentLibrary
from repositories import (
    crawl_task_repo,
    crawled_page_repo,
    doc_upload_repo,
    document_api_repo,
    document_library_repo,
    document_repo,
)
from services.docs_mcp_client import DocsMcpError, docs_mcp_client

logger = logging.getLogger(__name__)


def _serialize_library(lib: DocumentLibrary) -> dict:
    return {
        "id": lib.id,
        "name": lib.name,
        "description": lib.description,
        "document_count": lib.document_count,
        "total_chunks": lib.total_chunks,
        "source_url": lib.source_url,
        "active_version": lib.active_version,
        "created_by": lib.created_by,
        "created_at": lib.created_at.isoformat() if lib.created_at else None,
        "updated_at": lib.updated_at.isoformat() if lib.updated_at else None,
    }


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


async def refresh_document_counts(session: AsyncSession, library_name: str) -> None:
    """从 documents 表重新计算文档数与分块总数，一并写回 document_libraries。

    total_chunks 与 document_count 同源同刷，防止只更新其一导致库卡片分块数长期漂移。
    """
    library = await document_library_repo.find_by_name(session, library_name)
    if library is None:
        return
    document_count, total_chunks = await document_repo.count_and_chunks_by_library(
        session, library_name
    )
    await document_library_repo.update_counts(
        session, library.id, document_count, total_chunks
    )


async def list_libraries(session: AsyncSession) -> list[dict]:
    """获取所有知识库列表，返回序列化字典。"""
    libraries = await document_library_repo.list_all(session)
    return [_serialize_library(lib) for lib in libraries]


async def search_libraries(
    session: AsyncSession,
    keyword: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """关键字搜索知识库，返回分页结果。"""
    total = await document_library_repo.count_search(session, keyword)
    items = await document_library_repo.search(session, keyword, page, page_size)
    return {
        "items": [_serialize_library(lib) for lib in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_library_by_id(session: AsyncSession, library_id: int) -> dict:
    """根据 ID 获取知识库详情。"""
    library = await document_library_repo.find_by_id(session, library_id)
    if library is None:
        raise NotFoundError("document_library", library_id)
    return _serialize_library(library)


async def create_library(
    session: AsyncSession,
    name: str,
    description: str = "",
    created_by: int | None = None,
) -> dict:
    """创建知识库。"""
    existing = await document_library_repo.find_by_name(session, name)
    if existing is not None:
        raise ConflictError("知识库名称已存在")
    library = DocumentLibrary(
        name=name,
        description=description,
        created_by=created_by,
    )
    library = await document_library_repo.create(session, library)
    await session.commit()
    await session.refresh(library)
    return _serialize_library(library)


async def update_library(
    session: AsyncSession,
    library_id: int,
    name: str | None = None,
    description: str | None = None,
) -> dict:
    """更新知识库。"""
    library = await document_library_repo.find_by_id(session, library_id)
    if library is None:
        raise NotFoundError("document_library", library_id)
    if name is not None and name.lower() != library.name.lower():
        existing = await document_library_repo.find_by_name(session, name)
        if existing is not None:
            raise ConflictError("知识库名称已存在")
    await document_library_repo.update_library_info(
        session, library_id, name, description
    )
    await session.commit()
    await session.refresh(library)
    return _serialize_library(library)


async def delete_library(session: AsyncSession, library_id: int) -> None:
    """删除知识库及其全部关联数据。

    平台 DB 先批量级联删除并 commit，再尽力同步 docs-mcp（外部失败仅记日志，
    不回滚——平台 DB 是唯一数据源）。document_count 随库删除，无需 refresh。
    specs/endpoints 跟随 documents 的 ondelete=CASCADE 自动清除。
    """
    library = await document_library_repo.find_by_id(session, library_id)
    if library is None:
        raise NotFoundError("document_library", library_id)
    name = library.name
    await document_repo.delete_by_library(session, name)
    await doc_upload_repo.delete_by_library(session, name)
    await crawled_page_repo.delete_by_library(session, name)
    await crawl_task_repo.delete_by_library(session, name)
    await document_api_repo.delete_jobs_by_library(session, name)
    await document_library_repo.delete_library(session, library_id)
    await session.commit()
    await remove_docs_mcp_library(name)


async def remove_docs_mcp_library(library_name: str) -> None:
    """尽力清理 docs-mcp 中该库的全部版本向量，失败不阻断删除流程。"""
    try:
        libraries = await docs_mcp_client.list_libraries()
    except DocsMcpError:
        logger.warning(
            "docs-mcp list_libraries failed during library delete",
            extra={"library": library_name},
        )
        return
    for lib in libraries:
        if lib.get("library") != library_name:
            continue
        for ver in lib.get("versions", []):
            ref = ver.get("ref") or {}
            version = ref.get("version") or ""
            try:
                await docs_mcp_client.remove_version(library_name, version)
            except DocsMcpError:
                logger.warning(
                    "docs-mcp remove_version failed during library delete",
                    extra={"library": library_name, "version": version},
                )
