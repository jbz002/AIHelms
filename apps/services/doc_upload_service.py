"""文档上传服务：提取文件内容，调用 docs-mcp ingest-raw 入库。"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from models.db import DocUploadRecord
from repositories import doc_upload_repo
from services.docs_mcp_client import DocsMcpError, docs_mcp_client

logger = logging.getLogger(__name__)

# v1 支持的纯文本格式（无需额外依赖即可提取）
SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".xml": "text/xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".log": "text/plain",
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".sql": "text/x-sql",
    ".sh": "text/x-shellscript",
    ".rst": "text/x-rst",
    ".toml": "text/x-toml",
    ".ini": "text/x-ini",
    ".cfg": "text/x-ini",
    ".env": "text/plain",
    ".gitignore": "text/plain",
    ".dockerignore": "text/plain",
}


def _detect_content_type(file_name: str) -> str:
    """根据文件扩展名推断 MIME 类型。"""
    import os

    _, ext = os.path.splitext(file_name.lower())
    return SUPPORTED_EXTENSIONS.get(ext, "text/plain")


def _extract_text(file_bytes: bytes, file_name: str) -> str:
    """从文件字节中提取文本内容。v1 仅支持纯文本格式。"""

    # 尝试 UTF-8 解码，失败则尝试 GBK（中文文档常见）
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    raise ValueError(f"无法解码文件 {file_name}，仅支持文本格式")


def _serialize_record(record: DocUploadRecord) -> dict:
    return {
        "id": record.id,
        "library": record.library,
        "version": record.version,
        "file_name": record.file_name,
        "file_size": record.file_size,
        "content_type": record.content_type,
        "status": record.status,
        "chunk_count": record.chunk_count,
        "error_message": record.error_message,
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
    }


async def upload_document(
    session: AsyncSession,
    file_bytes: bytes,
    file_name: str,
    library: str,
    version: str | None,
    created_by: int | None,
) -> dict:
    """上传文档：提取文本 → 入库 docs-mcp → 记录到平台 DB。"""
    content_type = _detect_content_type(file_name)

    # 创建 DB 记录
    record = DocUploadRecord(
        library=library,
        version=version or "",
        file_name=file_name,
        file_size=len(file_bytes),
        content_type=content_type,
        status="pending",
        created_by=created_by,
    )
    record = await doc_upload_repo.create(session, record)

    try:
        # 提取文本
        content = _extract_text(file_bytes, file_name)

        # 调 docs-mcp ingest-raw（docs-mcp 负责分块 + embedding + 存储）
        result = await docs_mcp_client.ingest_raw(
            library=library,
            version=version,
            documents=[
                {
                    "url": f"local://{file_name}",
                    "title": file_name,
                    "contentType": content_type,
                    "content": content,
                }
            ],
        )

        ingested = result.get("ingested", 1) if isinstance(result, dict) else 1
        await doc_upload_repo.update_status(
            session, record.id, "completed", chunk_count=ingested
        )
        await session.refresh(record)
        return _serialize_record(record)

    except DocsMcpError as e:
        logger.error("docs-mcp ingest-raw failed: %s", str(e))
        await doc_upload_repo.update_status(
            session, record.id, "failed", error_message=str(e)[:500]
        )
        await session.refresh(record)
        return _serialize_record(record)

    except Exception as e:
        logger.error("document upload failed: %s", str(e), exc_info=True)
        await doc_upload_repo.update_status(
            session, record.id, "failed", error_message=str(e)[:500]
        )
        await session.refresh(record)
        return _serialize_record(record)


async def list_upload_records(
    session: AsyncSession,
    library: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询上传记录。"""
    if library:
        items = await doc_upload_repo.list_by_library(session, library, page, page_size)
        total = await doc_upload_repo.count_by_library(session, library)
    else:
        # 按 ID 倒序查全部
        from sqlalchemy import select

        stmt = (
            select(DocUploadRecord)
            .order_by(DocUploadRecord.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        count_stmt = select(DocUploadRecord.id)
        count_result = await session.execute(count_stmt)
        total = len(count_result.scalars().all())

    return {
        "items": [_serialize_record(r) for r in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
