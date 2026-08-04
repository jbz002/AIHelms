"""crawl_task 暂停/恢复状态机测试。

verify update_status 允许 crawling↔paused、ingesting↔paused、paused→failed,
拒绝非法迁移(如 pending→paused)。需 middleware(DB)运行。

每个用例自建 NullPool engine 并在结束时 dispose,避免全局 async engine 的连接
跨 asyncio.run(不同 event loop)复用导致 "another operation in progress"。
"""

import asyncio
from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings
from models.db import CrawlTask
from repositories import crawl_task_repo


def _make_task(status: str) -> CrawlTask:
    return CrawlTask(
        job_id=f"test-pause-{status}-{datetime.now().timestamp()}",
        library="test-pause-lib",
        version="",
        source_url="https://example.com",
        status=status,
        started_at=datetime.now() if status != "pending" else None,
    )


def _new_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _run(make_task_status: str, assertions) -> None:
    """创建任务 → 跑断言(收 session factory + task_id)→ 清理,单 asyncio.run。"""

    async def body():
        factory = _new_session_factory()
        try:
            async with factory() as s:
                task = await crawl_task_repo.create(s, _make_task(make_task_status))
                task_id = task.id
                await s.commit()
            try:
                await assertions(factory, task_id)
            finally:
                async with factory() as s:
                    await s.execute(delete(CrawlTask).where(CrawlTask.id == task_id))
                    await s.commit()
        finally:
            await factory().bind.dispose()

    asyncio.run(body())


def test_update_status_allows_crawling_pause_resume():
    """crawling → paused → crawling 合法。"""

    async def assertions(factory, task_id):
        async with factory() as s:
            await crawl_task_repo.update_status(
                s, task_id, "paused", paused_from="crawling"
            )
            await s.commit()
        async with factory() as s:
            t = await crawl_task_repo.find_by_id(s, task_id)
            assert t.status == "paused"
            assert t.paused_from == "crawling"

        async with factory() as s:
            await crawl_task_repo.update_status(s, task_id, "crawling")
            await s.commit()
        async with factory() as s:
            t = await crawl_task_repo.find_by_id(s, task_id)
            assert t.status == "crawling"
            assert t.paused_from is None

    _run("crawling", assertions)


def test_update_status_allows_ingesting_pause_resume():
    """ingesting → paused → ingesting 合法。"""

    async def assertions(factory, task_id):
        async with factory() as s:
            await crawl_task_repo.set_paused(s, task_id, "ingesting")
            await s.commit()
        async with factory() as s:
            t = await crawl_task_repo.find_by_id(s, task_id)
            assert t.status == "paused"

        async with factory() as s:
            await crawl_task_repo.update_status(s, task_id, "ingesting")
            await s.commit()
        async with factory() as s:
            t = await crawl_task_repo.find_by_id(s, task_id)
            assert t.status == "ingesting"

    _run("ingesting", assertions)


def test_update_status_paused_to_failed_allowed():
    """paused → failed 合法。"""

    async def assertions(factory, task_id):
        async with factory() as s:
            await crawl_task_repo.set_paused(s, task_id, "crawling")
            await s.commit()
        async with factory() as s:
            await crawl_task_repo.update_status(s, task_id, "failed", error_message="x")
            await s.commit()
        async with factory() as s:
            t = await crawl_task_repo.find_by_id(s, task_id)
            assert t.status == "failed"

    _run("crawling", assertions)


def test_update_status_rejects_pending_to_paused():
    """pending → paused 非法(guard 仅允许 crawling/ingesting/failed),状态保持 pending。"""

    async def assertions(factory, task_id):
        async with factory() as s:
            await crawl_task_repo.set_paused(s, task_id, "crawling")
            await s.commit()
        async with factory() as s:
            t = await crawl_task_repo.find_by_id(s, task_id)
            assert t.status == "pending"

    _run("pending", assertions)


def test_update_status_prevents_regression_to_paused_from_ingested():
    """ingested → paused 非法(ingested 优先级高于 paused,禁止回退)。"""

    async def assertions(factory, task_id):
        async with factory() as s:
            await crawl_task_repo.set_paused(s, task_id, "crawling")
            await s.commit()
        async with factory() as s:
            t = await crawl_task_repo.find_by_id(s, task_id)
            # ingested 不可暂停(guard 限定 crawling/ingesting/failed),状态不变
            assert t.status == "ingested"

    _run("ingested", assertions)
