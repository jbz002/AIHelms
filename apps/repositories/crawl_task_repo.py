"""crawl_tasks 表的数据库操作。"""

from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import CrawlTask


async def create(session: AsyncSession, task: CrawlTask) -> CrawlTask:
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return task


async def find_by_id(session: AsyncSession, task_id: int) -> CrawlTask | None:
    result = await session.execute(select(CrawlTask).where(CrawlTask.id == task_id))
    return result.scalar_one_or_none()


async def find_by_job_id(session: AsyncSession, job_id: str) -> CrawlTask | None:
    result = await session.execute(select(CrawlTask).where(CrawlTask.job_id == job_id))
    return result.scalar_one_or_none()


async def list_tasks(
    session: AsyncSession,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> list[CrawlTask]:
    stmt = select(CrawlTask).order_by(CrawlTask.id.desc())
    if status:
        stmt = stmt.where(CrawlTask.status == status)
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_tasks(session: AsyncSession, status: str | None = None) -> int:
    stmt = select(func.count()).select_from(CrawlTask)
    if status:
        stmt = stmt.where(CrawlTask.status == status)
    result = await session.execute(stmt)
    return result.scalar_one()


async def update_status(
    session: AsyncSession,
    task_id: int,
    status: str,
    **kwargs: object,
) -> None:
    values: dict[str, object] = {"status": status}
    if "error_message" in kwargs:
        values["error_message"] = kwargs["error_message"]
    if "pages_crawled" in kwargs:
        values["pages_crawled"] = kwargs["pages_crawled"]
    if "pages_total" in kwargs:
        values["pages_total"] = kwargs["pages_total"]
    if "current_url" in kwargs:
        values["current_url"] = kwargs["current_url"]
    if "pages_ingested" in kwargs:
        values["pages_ingested"] = kwargs["pages_ingested"]
    if status in ("crawling", "ingesting"):
        values["started_at"] = datetime.now()
    if status in ("crawled", "ingested", "failed"):
        values["finished_at"] = datetime.now()
    await session.execute(
        update(CrawlTask).where(CrawlTask.id == task_id).values(**values)
    )
    await session.flush()


async def increment_pages_crawled(session: AsyncSession, task_id: int) -> None:
    await session.execute(
        update(CrawlTask)
        .where(CrawlTask.id == task_id)
        .values(pages_crawled=CrawlTask.pages_crawled + 1)
    )
    await session.flush()


async def update_progress(
    session: AsyncSession,
    task_id: int,
    pages_total: int | None = None,
    pages_crawled: int | None = None,
    pages_ingested: int | None = None,
    current_url: str | None = None,
) -> None:
    """Update crawl task progress fields. Only non-None values are applied."""
    values: dict[str, object] = {}
    if pages_total is not None:
        values["pages_total"] = pages_total
    if pages_crawled is not None:
        values["pages_crawled"] = pages_crawled
    if pages_ingested is not None:
        values["pages_ingested"] = pages_ingested
    if current_url is not None:
        values["current_url"] = current_url
    if values:
        await session.execute(
            update(CrawlTask).where(CrawlTask.id == task_id).values(**values)
        )
        await session.flush()


async def delete_by_library(session: AsyncSession, library: str) -> int:
    """按 library 批量删除爬取任务，返回删除行数。"""
    stmt = delete(CrawlTask).where(
        func.lower(CrawlTask.library) == library.lower()
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.rowcount
