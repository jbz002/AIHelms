"""crawled_pages 表的数据库操作。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import CrawledPage


async def upsert_by_task_url(
    session: AsyncSession,
    crawl_task_id: int,
    url: str,
    **fields: object,
) -> CrawledPage:
    existing = await session.execute(
        select(CrawledPage).where(
            CrawledPage.crawl_task_id == crawl_task_id,
            CrawledPage.url == url,
        )
    )
    page = existing.scalar_one_or_none()
    if page:
        for key, value in fields.items():
            setattr(page, key, value)
    else:
        page = CrawledPage(crawl_task_id=crawl_task_id, url=url, **fields)
        session.add(page)
    await session.flush()
    await session.refresh(page)
    return page


async def list_by_task_id(
    session: AsyncSession,
    crawl_task_id: int,
    page: int = 1,
    page_size: int = 50,
) -> list[CrawledPage]:
    stmt = (
        select(CrawledPage)
        .where(CrawledPage.crawl_task_id == crawl_task_id)
        .order_by(CrawledPage.id.asc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_by_task_id(session: AsyncSession, crawl_task_id: int) -> int:
    stmt = select(func.count()).where(CrawledPage.crawl_task_id == crawl_task_id)
    result = await session.execute(stmt)
    return result.scalar_one()


async def get_for_ingest(
    session: AsyncSession, crawl_task_id: int
) -> list[CrawledPage]:
    stmt = (
        select(CrawledPage)
        .where(CrawledPage.crawl_task_id == crawl_task_id)
        .order_by(CrawledPage.id.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_by_task_id(session: AsyncSession, crawl_task_id: int) -> None:
    from sqlalchemy import delete

    await session.execute(
        delete(CrawledPage).where(CrawledPage.crawl_task_id == crawl_task_id)
    )
    await session.flush()
