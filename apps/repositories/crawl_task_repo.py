"""crawl_tasks 表的数据库操作。"""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import CrawlTask


async def create(session: AsyncSession, task: CrawlTask) -> CrawlTask:
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return task


async def find_by_id(session: AsyncSession, task_id: int) -> CrawlTask | None:
    result = await session.execute(
        select(CrawlTask).where(CrawlTask.id == task_id)
    )
    return result.scalar_one_or_none()


async def find_by_job_id(session: AsyncSession, job_id: str) -> CrawlTask | None:
    result = await session.execute(
        select(CrawlTask).where(CrawlTask.job_id == job_id)
    )
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
