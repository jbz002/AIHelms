"""文档上传服务：提取文件内容，调用 docs-mcp ingest-raw 入库。"""

import hashlib
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Document, DocUploadRecord
from repositories import doc_upload_repo, document_repo
from services import document_library_service
from services.docs_mcp_client import DocsMcpError, docs_mcp_client

logger = logging.getLogger(__name__)

# 纯文本格式（直接解码，无需 docling）
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

# 二进制格式（需要 docling-serve 转换）
BINARY_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".epub": "application/epub+zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}

ALL_SUPPORTED_EXTENSIONS: dict[str, str] = {**SUPPORTED_EXTENSIONS, **BINARY_EXTENSIONS}


def _detect_content_type(file_name: str) -> str:
    """根据文件扩展名推断 MIME 类型。"""
    import os

    _, ext = os.path.splitext(file_name.lower())
    return ALL_SUPPORTED_EXTENSIONS.get(ext, "application/octet-stream")


def _is_binary_format(file_name: str) -> bool:
    """判断文件是否为二进制格式（需要 docling-serve 转换）。"""
    import os

    _, ext = os.path.splitext(file_name.lower())
    return ext in BINARY_EXTENSIONS


async def _extract_text(file_bytes: bytes, file_name: str) -> str:
    """提取文本内容。纯文本直接解码，二进制格式通过 docling-serve 转换。"""
    if _is_binary_format(file_name):
        return await _extract_binary(file_bytes, file_name)
    return _extract_plain_text(file_bytes, file_name)


def _extract_plain_text(file_bytes: bytes, file_name: str) -> str:
    """纯文本文件直接解码。"""
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    raise ValueError(f"无法解码文件 {file_name}，仅支持文本格式")


async def _extract_binary(file_bytes: bytes, file_name: str) -> str:
    """二进制文件通过 docling-serve 转换为 Markdown。"""
    from services.docling_client import docling_client

    content_type = _detect_content_type(file_name)
    return await docling_client.convert_file(
        file_bytes=file_bytes,
        file_name=file_name,
        content_type=content_type,
        do_ocr=True,
    )


def _serialize_record(record: DocUploadRecord) -> dict:
    extracted_preview = ""
    if record.extracted_content:
        extracted_preview = record.extracted_content[:200]
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
        "extracted_content_preview": extracted_preview,
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
    auto_ingest: bool = False,
) -> dict:
    """上传文档：提取文本内容 → 存入平台 DB。

    若 auto_ingest=True，提取后自动调用 ingest_upload 入库。
    若 auto_ingest=False，仅提取并保存，返回 status=extracted 供后续手动入库。
    """
    content_type = _detect_content_type(file_name)

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

    # 同步知识库到平台 DB
    await document_library_service.ensure_library_exists(
        session=session, name=library, created_by=created_by
    )

    try:
        await doc_upload_repo.update_status(session, record.id, "extracting")
        content = await _extract_text(file_bytes, file_name)

        await doc_upload_repo.update_extracted_content(session, record.id, content)
        await doc_upload_repo.update_status(session, record.id, "extracted")
        await session.refresh(record)

        # 同步建立 Document（ingest_status='pending'），让文档列表/统计可见入库状态
        await document_repo.upsert_by_source(
            session,
            "upload",
            record.id,
            title=record.file_name,
            content=content,
            library=record.library,
            version=record.version or "",
            created_by=record.created_by,
            chunk_count=0,
            metadata_={
                "file_name": record.file_name,
                "content_type": record.content_type,
                "file_size": record.file_size,
            },
        )

        if auto_ingest:
            return await ingest_upload(session, record.id)

        return _serialize_record(record)

    except Exception as e:
        logger.error("document extraction failed: %s", str(e), exc_info=True)
        await doc_upload_repo.update_status(
            session, record.id, "failed", error_message=str(e)[:500]
        )
        await session.refresh(record)
        return _serialize_record(record)


async def ingest_upload(session: AsyncSession, record_id: int) -> dict:
    """将已提取内容的上传记录入库到 docs-mcp。支持 failed 状态重试。"""
    record = await doc_upload_repo.find_by_id(session, record_id)
    if record is None:
        raise ValueError(f"upload record {record_id} not found")
    if record.status not in ("extracted", "failed"):
        raise ValueError(
            f"upload record status is {record.status}, expected extracted or failed"
        )
    if not record.extracted_content:
        raise ValueError("文档内容为空，请重新上传")

    await doc_upload_repo.update_status(session, record_id, "ingesting")
    await session.refresh(record)

    try:
        documents = [
            {
                "url": f"local://{record.file_name}",
                "title": record.file_name,
                "contentType": record.content_type,
                "content": record.extracted_content,
            }
        ]

        result = await docs_mcp_client.ingest_raw(
            library=record.library,
            version=record.version or None,
            documents=documents,
        )

        # docs-mcp ingest-raw 返回 { ingested: 文档数, chunks: 块数 }
        # chunks 为真块数；旧版 docs-mcp 无该字段时回退 ingested（文档数）
        num_chunks = (
            (result.get("chunks") or result.get("ingested") or 1)
            if isinstance(result, dict)
            else 1
        )
        await doc_upload_repo.update_status(
            session, record.id, "completed", chunk_count=num_chunks
        )
        await session.refresh(record)

        # 同步文档记录到平台 DB：翻转 upload 阶段建立的 pending Document
        existing = await document_repo.find_by_source(session, "upload", record.id)
        if existing is None:
            # 兜底：upload 阶段未建 Document 时补建为 ingested
            content_hash = hashlib.sha256(
                record.extracted_content.encode("utf-8")
            ).hexdigest()
            doc = Document(
                title=record.file_name,
                content=record.extracted_content,
                library=record.library,
                version=record.version,
                source_type="upload",
                source_id=record.id,
                chunk_count=num_chunks,
                ingest_status="ingested",
                content_hash=content_hash,
                created_by=record.created_by,
                metadata_={
                    "file_name": record.file_name,
                    "content_type": record.content_type,
                    "file_size": record.file_size,
                },
            )
            await document_repo.create(session, doc)
        else:
            await document_repo.update_ingest_status(
                session, existing.id, "ingested", chunk_count=num_chunks
            )

        await document_library_service.refresh_document_counts(session, record.library)

        return _serialize_record(record)

    except DocsMcpError as e:
        logger.error("docs-mcp ingest-raw failed: %s", str(e))
        await doc_upload_repo.update_status(
            session, record.id, "failed", error_message=str(e)[:500]
        )
        await session.refresh(record)
        return _serialize_record(record)


async def delete_upload(session: AsyncSession, record_id: int) -> None:
    """删除一条上传记录。"""
    await doc_upload_repo.delete(session, record_id)


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
        items = await doc_upload_repo.list_all(session, page, page_size)
        total = await doc_upload_repo.count_all(session)

    return {
        "items": [_serialize_record(r) for r in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_extracted_content(
    session: AsyncSession, record_id: int
) -> str | None:
    """返回上传记录的完整提取内容。"""
    record = await doc_upload_repo.find_by_id(session, record_id)
    if record is None:
        return None
    return record.extracted_content
