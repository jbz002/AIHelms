"""Skill 版本漂移检测 Celery 任务（S9）。

每日定时批量扫描 source_type='url' 且 active 的版本，重算 hash 比对、回写 drift 字段。
业务逻辑在 skill_drift_service，任务只负责桥接同步 worker 与异步 session。
"""

import asyncio
import logging

from celery.schedules import crontab

from celery_app import celery_app
from core.database import get_worker_session_factory
from services import skill_drift_service

logger = logging.getLogger(__name__)

# 批量任务：逐版本下载，宽松时限
_BATCH_SOFT_TIME_LIMIT = 1800  # 30 min
_BATCH_TIME_LIMIT = 2100


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    name="skill_drift.check_batch",
    acks_late=True,
    max_retries=0,
    soft_time_limit=_BATCH_SOFT_TIME_LIMIT,
    time_limit=_BATCH_TIME_LIMIT,
)
def run_drift_check_batch(self) -> dict:
    """每日定时漂移检测入口。单版本失败隔离，整体不中断。"""
    return _run_async(_run_batch())


async def _run_batch() -> dict:
    try:
        async with get_worker_session_factory()() as session:
            return await skill_drift_service.check_drift_batch(session)
    except Exception:
        logger.exception("skill drift batch worker failed")
        raise


# beat 注册（spread-merge，仿 mcp_tasks，避免覆盖主 schedule）
celery_app.conf.beat_schedule = {
    **getattr(celery_app.conf, "beat_schedule", {}),
    "skill-drift-check-batch": {
        "task": "skill_drift.check_batch",
        "schedule": crontab(hour=5, minute=30),
    },
}
