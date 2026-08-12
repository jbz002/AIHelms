"""模型相关定时任务。

目前仅含 LiteLLM deployment 反向对账:拉 LiteLLM 真值与 aihelms 追踪集合求差,
清理 aihelms 不再追踪的孤儿 deployment(历史 re-sync/改名/置空重建遗留)。
"""

import asyncio
import logging

from celery_app import celery_app
from core.database import get_worker_session_factory
from services import model_service

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="model.reconcile_litellm")
def reconcile_litellm() -> dict:
    return _run_async(_reconcile())


async def _reconcile() -> dict:
    try:
        async with get_worker_session_factory()() as session:
            return await model_service.reconcile_litellm_deployments(session)
    except Exception:
        logger.error("failed to reconcile litellm deployments", exc_info=True)
        return {}
