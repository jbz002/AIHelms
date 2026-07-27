import asyncio
import logging

from billiard.exceptions import SoftTimeLimitExceeded

from celery_app import celery_app
from core.config import settings
from core.database import get_worker_session_factory
from services import document_api_service

logger = logging.getLogger(__name__)

EXTRACT_SOFT_TIME_LIMIT = settings.api_extract_timeout_seconds + 30
EXTRACT_TIME_LIMIT = settings.api_extract_timeout_seconds + 90


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
