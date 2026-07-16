"""docs-mcp 事件后台订阅器。

独立于浏览器 SSE 连接，常驻消费 docs-mcp `/api/events`：
page-scraped 落 crawled_pages，job-status-change 更新 crawl_tasks 状态，
auto_ingest 时把入库交给 Celery。

多 worker 部署下用 PostgreSQL advisory lock 保证全局唯一订阅器。
"""

import asyncio
import json
import logging

import httpx
from sqlalchemy import text

from core.config import settings
from core.database import async_session
from services import crawl_task_service

logger = logging.getLogger(__name__)

# advisory lock 固定 key，保证全局只有一个订阅器在跑
_ADVISORY_KEY = 91020250716
_RECONNECT_BACKOFF = 2.0
_RECONNECT_MAX = 60.0


async def run_docs_mcp_event_subscriber() -> None:
    """订阅器入口：抢 advisory lock，抢到才跑消费循环，否则退出。"""
    async with async_session() as lock_session:
        got = (
            await lock_session.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": _ADVISORY_KEY}
            )
        ).scalar()
        if not got:
            logger.info("docs-mcp subscriber: lock held by another worker, skip")
            return

        logger.info("docs-mcp subscriber: lock acquired, starting consume loop")
        try:
            await _consume_loop()
        except asyncio.CancelledError:
            raise
        finally:
            await lock_session.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": _ADVISORY_KEY}
            )


async def _consume_loop() -> None:
    url = f"{settings.docs_mcp_server_url.rstrip('/')}/api/events"
    backoff = _RECONNECT_BACKOFF

    while True:
        try:
            timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
            async with httpx.AsyncClient(timeout=timeout, proxy=None) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code >= 400:
                        raise RuntimeError(f"upstream {resp.status_code}")
                    backoff = _RECONNECT_BACKOFF
                    current_event: str | None = None
                    current_data = ""
                    async for line in resp.aiter_lines():
                        if line.startswith("event: "):
                            current_event = line[7:]
                        elif line.startswith("data: "):
                            current_data = line[6:]
                        elif line == "" and current_event:
                            await _dispatch_event(current_event, current_data)
                            current_event = None
                            current_data = ""
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "docs-mcp subscriber stream error: %s; reconnect in %ss", e, backoff
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_MAX)


async def _dispatch_event(event_name: str, data_str: str) -> None:
    if event_name not in ("page-scraped", "job-status-change"):
        return
    try:
        payload = json.loads(data_str)
    except (json.JSONDecodeError, TypeError):
        return

    if event_name == "page-scraped":
        job_id = payload.get("id")
        if not job_id:
            return
        page = payload.get("page", {})
        try:
            async with async_session() as session:
                await crawl_task_service.handle_page_scraped(session, job_id, page)
                await session.commit()
        except Exception:
            logger.exception("handle page-scraped failed: job=%s", job_id)
        return

    # job-status-change
    job_id = payload.get("id")
    status = payload.get("status")
    if not job_id or not status:
        return
    error = payload.get("error")
    error_message = error.get("message") if isinstance(error, dict) else None

    task = None
    try:
        async with async_session() as session:
            task = await crawl_task_service.handle_job_completed(
                session, job_id, status, error_message
            )
            await session.commit()
    except Exception:
        logger.exception("handle job-status-change failed: job=%s", job_id)

    if task is not None and status == "completed" and task.auto_ingest:
        from tasks.doc_tasks import ingest_crawl_task

        ingest_crawl_task.delay(task.id)
        logger.info("auto ingest dispatched for crawl task %s", task.id)
