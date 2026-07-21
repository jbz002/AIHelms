"""存储删除补偿定时任务。

每小时扫描 pending 补偿记录，重试删文件；成功标 done，失败 retries+1，达上限标 failed。
"""

import asyncio
import logging
import os

from celery_app import celery_app
from core.config import settings
from core.database import get_worker_session_factory
from repositories import storage_deletion_compensation_repo

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="storage_deletion_compensation.retry")
def retry_pending_compensations():
    _run_async(_retry())


async def _retry() -> None:
    max_retries = settings.storage_compensation_max_retries
    async with get_worker_session_factory()() as session:
        pending = await storage_deletion_compensation_repo.list_pending(
            session, limit=100
        )
        for comp in pending:
            if not os.path.exists(comp.storage_path):
                # 文件已不存在（曾成功或外部清理），直接标 done
                await storage_deletion_compensation_repo.mark_done(session, comp.id)
                continue
            try:
                os.remove(comp.storage_path)
            except OSError as exc:
                status = await storage_deletion_compensation_repo.inc_retry(
                    session, comp.id, str(exc), max_retries
                )
                logger.warning(
                    "compensation retry failed id=%s status=%s", comp.id, status
                )
            else:
                await storage_deletion_compensation_repo.mark_done(session, comp.id)
        await session.commit()
    logger.info("storage compensation retry pass done, processed=%s", len(pending))
