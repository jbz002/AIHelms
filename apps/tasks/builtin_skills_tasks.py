"""S8 · 内置 Skills 同步 Celery 任务。

启动时（lifespan）或 admin 手动触发一次性同步 manifest 中的官方 skill。
业务逻辑在 builtin_skills_service，任务只负责桥接同步 worker 与异步 session。
无 beat 注册（非周期）。
"""

import asyncio
import logging

from celery_app import celery_app
from core.database import get_worker_session_factory
from services import builtin_skills_service

logger = logging.getLogger(__name__)

_SOFT_TIME_LIMIT = 1800  # 30 min：含下载/解析/发布，宽松时限
_TIME_LIMIT = 2100


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    name="builtin_skills.sync_all",
    acks_late=True,
    max_retries=0,
    soft_time_limit=_SOFT_TIME_LIMIT,
    time_limit=_TIME_LIMIT,
)
def sync_builtin_skills(self) -> dict:
    """一次性同步内置 skills。单条失败隔离，整体不中断。"""
    return _run_async(_run_sync())


async def _run_sync() -> dict:
    try:
        async with get_worker_session_factory()() as session:
            return await builtin_skills_service.sync_all(session)
    except Exception:
        logger.exception("builtin skills sync worker failed")
        raise
