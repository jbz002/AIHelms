"""crawl_tasks 表的数据库操作。"""

from datetime import datetime

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import CrawlTask

# 状态优先级:单向状态机 guard 用(pending→crawling→crawled→ingesting→ingested)。
# update_status 只允许前进或转 failed,禁止回退(防 SSE/beat 竞态把 ingesting 写回 crawled)。
# paused=-1:任何运行态恢复都满足前进条件;进入 paused 走专门分支(见 update_status)。
_STATUS_PRIORITY: dict[str, int] = {
    "pending": 0,
    "crawling": 1,
    "crawled": 2,
    "ingesting": 3,
    "ingested": 4,
    "paused": -1,
}


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
    if "paused_from" in kwargs:
        values["paused_from"] = kwargs["paused_from"]
    if status in ("crawling", "ingesting"):
        values["started_at"] = datetime.now()
    if status in ("crawled", "ingested", "failed"):
        values["finished_at"] = datetime.now()
    # 清除暂停相位标记:一旦离开 paused,paused_from 失效(用 None 覆盖)。
    if status != "paused" and "paused_from" not in kwargs:
        values["paused_from"] = None

    # 状态机单向 guard:status 只能前进或转 failed,禁止回退。
    # 防 sync_task_status 与 SSE 竞态(读后网络往返期间状态已前进)把 ingesting 写回 crawled。
    # failed↔任意 自由(支持失败重试)。0 行 update 时 started_at/finished_at 也不动。
    # paused 单独分支:仅允许从 crawling/ingesting/failed 暂停。
    where_clauses: list[object] = [CrawlTask.id == task_id]
    if status == "paused":
        where_clauses.append(CrawlTask.status.in_(("crawling", "ingesting", "failed")))
    elif status != "failed":
        cur_priority = case(
            (CrawlTask.status == "pending", 0),
            (CrawlTask.status == "crawling", 1),
            (CrawlTask.status == "crawled", 2),
            (CrawlTask.status == "ingesting", 3),
            (CrawlTask.status == "ingested", 4),
            (CrawlTask.status == "paused", -1),
            else_=0,
        )
        where_clauses.append(
            or_(
                CrawlTask.status == "failed",
                cur_priority <= _STATUS_PRIORITY.get(status, 0),
            )
        )
    await session.execute(update(CrawlTask).where(*where_clauses).values(**values))
    await session.flush()


async def set_paused(session: AsyncSession, task_id: int, paused_from: str) -> None:
    """标记任务为暂停,并记录暂停相位(crawling|ingesting),供恢复决定后续动作。"""
    await update_status(session, task_id, "paused", paused_from=paused_from)


async def update_job_id(session: AsyncSession, task_id: int, job_id: str) -> None:
    """回写 docs-mcp 重启恢复后产生的新 jobId。"""
    await session.execute(
        update(CrawlTask).where(CrawlTask.id == task_id).values(job_id=job_id)
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
    pages_backfilled: int | None = None,
    pages_empty: int | None = None,
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
    if pages_backfilled is not None:
        values["pages_backfilled"] = pages_backfilled
    if pages_empty is not None:
        values["pages_empty"] = pages_empty
    if values:
        await session.execute(
            update(CrawlTask).where(CrawlTask.id == task_id).values(**values)
        )
        await session.flush()


async def delete_by_library_version(
    session: AsyncSession, library: str, version: str
) -> int:
    """按 library + version 批量删除爬取任务，返回删除行数。"""
    stmt = delete(CrawlTask).where(
        func.lower(CrawlTask.library) == library.lower(),
        CrawlTask.version == version,
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.rowcount


async def delete_by_library(session: AsyncSession, library: str) -> int:
    """按 library 批量删除爬取任务，返回删除行数。"""
    stmt = delete(CrawlTask).where(func.lower(CrawlTask.library) == library.lower())
    result = await session.execute(stmt)
    await session.flush()
    return result.rowcount
