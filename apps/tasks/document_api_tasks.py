import asyncio
import logging

from billiard.exceptions import SoftTimeLimitExceeded

from celery_app import celery_app
from core.config import settings
from core.database import get_worker_session_factory
from services import (
    document_api_batch_service,
    document_api_classify_service,
    document_api_service,
)

logger = logging.getLogger(__name__)

EXTRACT_SOFT_TIME_LIMIT = settings.api_extract_timeout_seconds + 30
EXTRACT_TIME_LIMIT = settings.api_extract_timeout_seconds + 90
BATCH_SOFT_TIME_LIMIT = settings.api_extract_timeout_seconds * 10 + 120
BATCH_TIME_LIMIT = BATCH_SOFT_TIME_LIMIT + 120
CLASSIFY_SOFT_TIME_LIMIT = settings.api_classify_timeout_seconds + 60
CLASSIFY_TIME_LIMIT = CLASSIFY_SOFT_TIME_LIMIT + 90


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    name="doc.extract_api_interfaces",
    acks_late=True,
    max_retries=0,
    soft_time_limit=EXTRACT_SOFT_TIME_LIMIT,
    time_limit=EXTRACT_TIME_LIMIT,
)
def extract_api_interfaces_task(self, spec_pk: int) -> None:
    try:
        _run_async(_run(spec_pk))
    except SoftTimeLimitExceeded:
        logger.exception("document api extraction timed out: spec_pk=%s", spec_pk)
        _run_async(
            document_api_service.fail_spec_by_id(
                spec_pk, "接口提取执行超时，请稍后重试"
            )
        )
        raise
    except Exception:
        logger.exception("document api extraction task failed: spec_pk=%s", spec_pk)
        _run_async(
            document_api_service.fail_spec_by_id(
                spec_pk, "接口提取任务执行失败，请稍后重试"
            )
        )
        raise


async def _run(spec_pk: int) -> None:
    try:
        async with get_worker_session_factory()() as session:
            await document_api_service.process_extraction(session, spec_pk)
    except Exception:
        logger.exception("document api extraction worker failed: spec_pk=%s", spec_pk)
        raise


@celery_app.task(
    bind=True,
    name="doc.extract_library_interfaces",
    acks_late=True,
    max_retries=0,
    soft_time_limit=BATCH_SOFT_TIME_LIMIT,
    time_limit=BATCH_TIME_LIMIT,
)
def extract_library_interfaces_task(self, job_pk: int) -> None:
    """库级批量提取：顺序处理库内每个 ingested 文档。"""
    try:
        _run_async(_run_batch(job_pk))
    except SoftTimeLimitExceeded:
        logger.exception("library batch extraction timed out: job_pk=%s", job_pk)
        _run_async(
            document_api_batch_service.fail_batch_by_id(
                job_pk, "批量提取执行超时，请稍后重试"
            )
        )
        raise
    except Exception:
        logger.exception("library batch extraction task failed: job_pk=%s", job_pk)
        _run_async(
            document_api_batch_service.fail_batch_by_id(
                job_pk, "批量提取任务执行失败，请稍后重试"
            )
        )
        raise


async def _run_batch(job_pk: int) -> None:
    try:
        async with get_worker_session_factory()() as session:
            await document_api_batch_service.process_library_extraction(session, job_pk)
    except Exception:
        logger.exception("library batch extraction worker failed: job_pk=%s", job_pk)
        raise


@celery_app.task(
    bind=True,
    name="doc.classify_library_interfaces",
    acks_late=True,
    max_retries=0,
    soft_time_limit=CLASSIFY_SOFT_TIME_LIMIT,
    time_limit=CLASSIFY_TIME_LIMIT,
)
def classify_library_interfaces_task(self, job_pk: int) -> None:
    """库级 AI 分类：统一归类库内全部接口到业务模块。"""
    try:
        _run_async(_run_classify(job_pk))
    except SoftTimeLimitExceeded:
        logger.exception("library classification timed out: job_pk=%s", job_pk)
        _run_async(
            document_api_classify_service.fail_category_by_id(
                job_pk, "接口分类执行超时，请稍后重试"
            )
        )
        raise
    except Exception:
        logger.exception("library classification task failed: job_pk=%s", job_pk)
        _run_async(
            document_api_classify_service.fail_category_by_id(
                job_pk, "接口分类任务执行失败，请稍后重试"
            )
        )
        raise


async def _run_classify(job_pk: int) -> None:
    try:
        async with get_worker_session_factory()() as session:
            await document_api_classify_service.process_classification(session, job_pk)
    except Exception:
        logger.exception("library classification worker failed: job_pk=%s", job_pk)
        raise
