"""爬取任务服务：crawl-only 模式的任务管理、页面收集、批量入库。"""

import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import CrawledPage, CrawlTask
from repositories import crawl_task_repo, crawled_page_repo
from services.docs_mcp_client import DocsMcpError, docs_mcp_client

logger = logging.getLogger(__name__)

INGEST_BATCH_SIZE = 50


def _serialize_task(task: CrawlTask) -> dict:
    return {
        "id": task.id,
        "job_id": task.job_id,
        "library": task.library,
        "version": task.version,
        "source_url": task.source_url,
        "status": task.status,
        "pages_total": task.pages_total,
        "pages_crawled": task.pages_crawled,
        "error_message": task.error_message,
        "created_by": task.created_by,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


def _serialize_page(page: CrawledPage) -> dict:
    return {
        "id": page.id,
        "crawl_task_id": page.crawl_task_id,
        "url": page.url,
        "title": page.title,
        "source_content_type": page.source_content_type,
        "content_type": page.content_type,
        "text_content": page.text_content[:200] if page.text_content else "",
        "chunks_count": len(page.chunks) if page.chunks else 0,
        "depth": page.depth,
        "created_at": page.created_at.isoformat() if page.created_at else None,
    }


async def create_crawl_task(
    session: AsyncSession,
    url: str,
    library: str,
    version: str | None,
    scraper_options: dict,
    created_by: int | None,
    auto_ingest: bool = False,
) -> dict:
    """创建 crawl-only 任务：写入平台 DB → 调 docs-mcp scrape（crawlOnly=true）。"""
    task = CrawlTask(
        library=library,
        version=version or "",
        source_url=url,
        status="pending",
        scraper_options=scraper_options,
        created_by=created_by,
        auto_ingest=auto_ingest,
    )
    task = await crawl_task_repo.create(session, task)

    try:
        options = dict(scraper_options)
        options["crawlOnly"] = True
        result = await docs_mcp_client.enqueue_scrape_job(
            library=library,
            version=version,
            options=options,
        )
        job_id = result.get("jobId", "") if isinstance(result, dict) else ""
        await crawl_task_repo.update_status(session, task.id, "crawling")
        task.job_id = job_id
        await session.flush()
        await session.refresh(task)
    except DocsMcpError as e:
        logger.error("create crawl task failed: %s", str(e))
        await crawl_task_repo.update_status(
            session, task.id, "failed", error_message=str(e)[:500]
        )
        await session.refresh(task)

    return _serialize_task(task)


async def handle_page_scraped(
    session: AsyncSession,
    job_id: str,
    page_data: dict,
) -> None:
    """处理 page-scraped SSE 事件：持久化页面数据。"""
    task = await crawl_task_repo.find_by_job_id(session, job_id)
    if task is None:
        return

    page = page_data.get("page", {})
    await crawled_page_repo.upsert_by_task_url(
        session,
        crawl_task_id=task.id,
        url=page.get("url", ""),
        title=page.get("title", ""),
        source_content_type=page.get("sourceContentType", ""),
        content_type=page.get("contentType", ""),
        text_content=page.get("textContent", ""),
        links=page.get("links", []),
        chunks=page.get("chunks", []),
        depth=page.get("depth", 0),
        etag=page.get("etag"),
        last_modified=page.get("lastModified"),
    )
    await crawl_task_repo.increment_pages_crawled(session, task.id)


async def handle_job_completed(
    session: AsyncSession,
    job_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """处理 job-status-change SSE 事件：更新爬取任务状态。"""
    task = await crawl_task_repo.find_by_job_id(session, job_id)
    if task is None:
        return

    if status == "completed":
        new_status = "crawled"
        await crawl_task_repo.update_status(session, task.id, new_status)
        await session.refresh(task)
        if task.auto_ingest:
            try:
                await ingest_crawl_task(session, task.id)
            except Exception as e:
                logger.error("auto ingest failed for crawl task %s: %s", task.id, str(e))
    elif status == "failed":
        await crawl_task_repo.update_status(
            session,
            task.id,
            "failed",
            error_message=error_message or "docs-mcp job failed",
        )
    elif status == "cancelled":
        await crawl_task_repo.update_status(
            session, task.id, "failed", error_message="cancelled"
        )


async def ingest_crawl_task(
    session: AsyncSession,
    task_id: int,
) -> dict:
    """批量入库：读取 crawled_pages → 调 docs-mcp ingest-raw。"""
    task = await crawl_task_repo.find_by_id(session, task_id)
    if task is None:
        raise ValueError(f"crawl task {task_id} not found")
    if task.status != "crawled":
        raise ValueError(f"crawl task status is {task.status}, expected 'crawled'")

    await crawl_task_repo.update_status(session, task_id, "ingesting")
    await session.refresh(task)

    pages = await crawled_page_repo.get_for_ingest(session, task_id)
    if not pages:
        await crawl_task_repo.update_status(
            session, task_id, "ingested"
        )
        await session.refresh(task)
        return _serialize_task(task)

    try:
        documents = [
            {
                "url": p.url,
                "title": p.title,
                "contentType": p.content_type or "text/markdown",
                "content": p.text_content,
            }
            for p in pages
        ]

        for i in range(0, len(documents), INGEST_BATCH_SIZE):
            batch = documents[i : i + INGEST_BATCH_SIZE]
            await docs_mcp_client.ingest_raw(
                library=task.library,
                version=task.version or None,
                documents=batch,
            )

        await crawl_task_repo.update_status(session, task_id, "ingested")
        await session.refresh(task)
        return _serialize_task(task)

    except DocsMcpError as e:
        logger.error("ingest crawl task failed: %s", str(e))
        await crawl_task_repo.update_status(
            session, task_id, "failed", error_message=str(e)[:500]
        )
        await session.refresh(task)
        return _serialize_task(task)


async def list_crawl_tasks(
    session: AsyncSession,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    items = await crawl_task_repo.list_tasks(session, status, page, page_size)
    total = await crawl_task_repo.count_tasks(session, status)
    return {
        "items": [_serialize_task(t) for t in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_crawl_task(session: AsyncSession, task_id: int) -> dict | None:
    task = await crawl_task_repo.find_by_id(session, task_id)
    if task is None:
        return None
    return _serialize_task(task)


async def list_crawl_pages(
    session: AsyncSession,
    task_id: int,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    pages = await crawled_page_repo.list_by_task_id(session, task_id, page, page_size)
    total = await crawled_page_repo.count_by_task_id(session, task_id)
    return {
        "items": [_serialize_page(p) for p in pages],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def delete_crawl_task(session: AsyncSession, task_id: int) -> None:
    await crawled_page_repo.delete_by_task_id(session, task_id)
    await session.execute(
        delete(CrawlTask).where(CrawlTask.id == task_id)
    )
    await session.flush()
