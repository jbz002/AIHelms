"""文档入库 Celery 任务：crawl 批量入库、上传文档入库。

入库是重操作（批量向量化），交给 Celery 跑，避免阻塞 SSE 订阅器或 API 请求。
"""

import asyncio
import logging

from celery_app import celery_app
from core.database import get_worker_session_factory

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="doc.ingest_crawl")
def ingest_crawl_task(task_id: int) -> None:
    """crawl task 批量入库。"""
    from services import crawl_task_service

    async def _run() -> None:
        async with get_worker_session_factory()() as session:
            try:
                await crawl_task_service.ingest_crawl_task(session, task_id)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    try:
        _run_async(_run())
    except Exception:
        logger.exception("celery ingest_crawl_task failed: task_id=%s", task_id)
        raise


@celery_app.task(name="doc.ingest_upload")
def ingest_upload_task(record_id: int) -> None:
    """上传文档入库。"""
    from services import doc_upload_service

    async def _run() -> None:
        async with get_worker_session_factory()() as session:
            try:
                await doc_upload_service.ingest_upload(session, record_id)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    try:
        _run_async(_run())
    except Exception:
        logger.exception("celery ingest_upload_task failed: record_id=%s", record_id)
        raise


@celery_app.task(name="doc.process_upload")
def process_upload_task(record_id: int, auto_ingest: bool = True) -> None:
    """批量上传文档后台处理：docling 提取 + 可选入库。"""
    from services import doc_upload_service

    async def _run() -> None:
        async with get_worker_session_factory()() as session:
            try:
                await doc_upload_service.process_upload(session, record_id, auto_ingest)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    try:
        _run_async(_run())
    except Exception:
        logger.exception("celery process_upload_task failed: record_id=%s", record_id)
        raise


@celery_app.task(name="doc.ingest_document")
def ingest_document_task(document_id: int) -> dict:
    """单文档入库到 docs-mcp。"""
    from services import document_service

    async def _run() -> dict:
        async with get_worker_session_factory()() as session:
            try:
                result = await document_service.ingest_document(session, document_id)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    try:
        return _run_async(_run())
    except Exception:
        logger.exception(
            "celery ingest_document_task failed: document_id=%s", document_id
        )
        raise


@celery_app.task(name="doc.ingest_batch")
def ingest_batch_task(
    library: str | None = None,
    source_type: str | None = None,
) -> dict:
    """批量入库：所有 pending/failed 文档。"""
    from services import document_service

    async def _run() -> dict:
        async with get_worker_session_factory()() as session:
            try:
                result = await document_service.ingest_batch(
                    session, library=library, source_type=source_type
                )
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    try:
        return _run_async(_run())
    except Exception:
        logger.exception("celery ingest_batch_task failed: library=%s", library)
        raise
