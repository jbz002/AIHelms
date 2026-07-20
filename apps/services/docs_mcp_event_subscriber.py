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
from sqlalchemy import select, text

from core.config import settings
from core.database import async_session
from services import crawl_task_service

logger = logging.getLogger(__name__)

# advisory lock 固定 key，保证全局只有一个订阅器在跑
_ADVISORY_KEY = 91020250716
_RECONNECT_BACKOFF = 2.0
_RECONNECT_MAX = 60.0

# 调试：记录最近 N 条 SSE 原始事件
_DEBUG_LAST_EVENTS: list[str] = []
_DEBUG_MAX = 20


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
    logger.info("docs-mcp subscriber: connecting to %s", url)
    backoff = _RECONNECT_BACKOFF

    while True:
        try:
            timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
            async with httpx.AsyncClient(timeout=timeout, proxy=None) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code >= 400:
                        raise RuntimeError(f"upstream {resp.status_code}")
                    logger.info(
                        "docs-mcp subscriber: connected, status=%d",
                        resp.status_code,
                    )
                    backoff = _RECONNECT_BACKOFF
                    current_event: str | None = None
                    current_data = ""
                    async for line in resp.aiter_lines():
                        if line.startswith("event: "):
                            current_event = line[7:]
                        elif line.startswith("data: "):
                            current_data = line[6:]
                        elif line == "" and current_event:
                            logger.debug(
                                "[SSE raw] event=%s data=%s",
                                current_event,
                                current_data[:500],
                            )
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
    _DEBUG_LAST_EVENTS.append(f"[{event_name}] {data_str[:300]}")
    if len(_DEBUG_LAST_EVENTS) > _DEBUG_MAX:
        _DEBUG_LAST_EVENTS.pop(0)

    # library-change / job-list-change 是通知性事件，忽略属于正常行为
    if event_name not in ("page-scraped", "job-status-change", "job-progress"):
        logger.debug("[SSE ignored] event=%s", event_name)
        if event_name == "library-change":
            await _reconcile_stale_crawling_tasks()
        return

    logger.info("[SSE received] event=%s data=%s", event_name, data_str[:500])

    try:
        payload = json.loads(data_str)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "[SSE] json parse failed for event=%s: %s",
            event_name,
            data_str[:200],
        )
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

    if event_name == "job-status-change":
        job_id = payload.get("id")
        status = payload.get("status")
        if not job_id or not status:
            return
        error = payload.get("error")
        error_message = error.get("message") if isinstance(error, dict) else None

        # 兜底：SSE 中 error 为 null 时从 REST API 获取实际错误信息
        if status == "failed" and not error_message and job_id:
            error_message = await _fetch_error_from_api(job_id)

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
        return

    if event_name == "job-progress":
        job_id = payload.get("id")
        if not job_id:
            return
        progress = payload.get("progress")
        if not progress or not isinstance(progress, dict):
            return
        try:
            async with async_session() as session:
                await crawl_task_service.handle_job_progress(session, job_id, progress)
                await session.commit()
        except Exception:
            logger.exception("handle job-progress failed: job=%s", job_id)
        return


async def _fetch_error_from_api(job_id: str) -> str | None:
    """从 docs-mcp REST API 兜底获取 job 的实际错误信息。"""
    try:
        from services.docs_mcp_client import docs_mcp_client

        detail = await docs_mcp_client.get_job_detail(job_id)
        if not isinstance(detail, dict):
            return None
        error = detail.get("error")
        if isinstance(error, dict):
            return error.get("message")
        if isinstance(error, str):
            return error
        err_msg = detail.get("errorMessage")
        if isinstance(err_msg, str) and err_msg:
            return err_msg
    except Exception:
        logger.debug("_fetch_error_from_api failed for job=%s", job_id)
    return None


async def _reconcile_stale_crawling_tasks() -> None:
    """检查长时间处于 crawling 状态的任务，从 docs-mcp API 同步真实状态。

    作为 SSE 丢事件（断连重连）的兜底机制：library-change 信号
    说明 docs-mcp 侧发生了状态变化，此时检查是否有遗漏的任务。
    """
    from datetime import datetime, timedelta, timezone

    from services.docs_mcp_client import docs_mcp_client

    try:
        async with async_session() as session:
            from models.db import CrawlTask

            cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
            result = await session.execute(
                select(CrawlTask).where(
                    CrawlTask.status == "crawling",
                    CrawlTask.started_at.isnot(None),
                    CrawlTask.started_at < cutoff,
                    CrawlTask.job_id != "",
                )
            )
            stale_tasks = list(result.scalars().all())
            if not stale_tasks:
                return

            logger.info(
                "reconcile: found %d stale crawling tasks", len(stale_tasks)
            )
            for task in stale_tasks:
                try:
                    detail = await docs_mcp_client.get_job_detail(task.job_id)
                    if not isinstance(detail, dict):
                        continue
                    remote_status = detail.get("status")
                    if remote_status not in ("completed", "failed", "cancelled"):
                        continue
                    error = detail.get("error")
                    error_message = None
                    if isinstance(error, dict):
                        error_message = error.get("message")
                    elif isinstance(error, str):
                        error_message = error
                    if not error_message:
                        error_message = detail.get("errorMessage")
                    synced = await crawl_task_service.sync_task_status(
                        session, task.id
                    )
                    if synced:
                        logger.info(
                            "reconcile: task %s synced to %s (was crawling)",
                            task.id,
                            synced.get("status_raw"),
                        )
                except Exception:
                    logger.debug(
                        "reconcile: failed for task %s job=%s",
                        task.id,
                        task.job_id,
                    )
            await session.commit()
    except Exception:
        logger.debug("reconcile_stale_crawling_tasks failed", exc_info=True)
