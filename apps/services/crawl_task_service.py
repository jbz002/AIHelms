"""爬取任务服务：crawl-only 模式的任务管理、页面收集、批量入库。"""

import hashlib
import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import CrawledPage, CrawlTask, Document
from repositories import crawl_task_repo, crawled_page_repo, document_repo
from services import document_library_service
from services.docs_mcp_client import DocsMcpError, docs_mcp_client

logger = logging.getLogger(__name__)

# docs-mcp Fastify 默认 bodyLimit 1MB，留半给 JSON/url/title 开销
INGEST_BYTE_BUDGET = 512 * 1024


def _chunk_by_bytes(pages: list[CrawledPage], budget: int) -> list[list[CrawledPage]]:
    """按累计 text_content 字节切批，单批 ≤ budget；单页超 budget 自成一批。"""
    batches: list[list[CrawledPage]] = []
    batch: list[CrawledPage] = []
    size = 0
    for p in pages:
        psize = len((p.text_content or "").encode("utf-8"))
        if batch and size + psize > budget:
            batches.append(batch)
            batch = [p]
            size = psize
        else:
            batch.append(p)
            size += psize
    if batch:
        batches.append(batch)
    return batches


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
        "pages_ingested": task.pages_ingested,
        "current_url": task.current_url,
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
    """创建 crawl-only 任务：先 enqueue 拿 job_id（crawlOnly=true），再写平台 DB。

    job_id 为 NOT NULL，必须先拿到再落库。
    latest 哨兵在此解析为具体版本，确保任务落到当时最新版本桶。
    """
    version = await docs_mcp_client.resolve_version(library, version)
    options = dict(scraper_options)
    options["crawlOnly"] = True
    options["version"] = version or ""

    try:
        result = await docs_mcp_client.enqueue_scrape_job(
            library=library,
            version=version,
            options=options,
        )
        job_id = result.get("jobId", "") if isinstance(result, dict) else ""
    except DocsMcpError as e:
        logger.error("create crawl task failed: %s", str(e))
        task = CrawlTask(
            library=library,
            version=version or "",
            source_url=url,
            job_id="",
            status="failed",
            error_message=str(e)[:500],
            scraper_options=scraper_options,
            created_by=created_by,
            auto_ingest=auto_ingest,
        )
        task = await crawl_task_repo.create(session, task)
        await session.refresh(task)
        return _serialize_task(task)

    task = CrawlTask(
        library=library,
        version=version or "",
        source_url=url,
        job_id=job_id,
        status="pending",
        scraper_options=scraper_options,
        created_by=created_by,
        auto_ingest=auto_ingest,
    )
    task = await crawl_task_repo.create(session, task)
    await crawl_task_repo.update_status(session, task.id, "crawling")
    await session.refresh(task)

    # 同步知识库到平台 DB
    await document_library_service.ensure_library_exists(
        session=session, name=library, created_by=created_by, source_url=url
    )

    return _serialize_task(task)


async def handle_job_progress(
    session: AsyncSession,
    job_id: str,
    progress: dict,
) -> None:
    """处理 job-progress SSE 事件：更新进度字段。

    progress 包含 pagesScraped, totalPages, totalDiscovered, currentUrl。
    totalPages 受 scraper_options.maxPages 限制。
    """
    logger.info(
        "handle_job_progress: job_id=%s progress_keys=%s",
        job_id,
        list(progress.keys()),
    )
    task = await crawl_task_repo.find_by_job_id(session, job_id)
    if task is None:
        logger.warning("handle_job_progress: task not found for job_id=%s", job_id)
        return

    total_pages = progress.get("totalPages", 0)
    pages_scraped = progress.get("pagesScraped", 0)
    current_url = progress.get("currentUrl", "")

    max_pages = task.scraper_options.get("maxPages") if task.scraper_options else None
    if max_pages and total_pages > 0:
        total_pages = min(total_pages, max_pages)

    await crawl_task_repo.update_progress(
        session,
        task.id,
        pages_total=total_pages,
        pages_crawled=pages_scraped,
        current_url=current_url,
    )


async def handle_page_scraped(
    session: AsyncSession,
    job_id: str,
    page: dict,
) -> None:
    """处理 page-scraped SSE 事件：持久化页面数据。

    page 为 SSE 事件里的 page 对象（url/title/textContent 等）。
    """
    task = await crawl_task_repo.find_by_job_id(session, job_id)
    if task is None:
        return

    crawled = await crawled_page_repo.upsert_by_task_url(
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

    # 同步建立 Document（ingest_status='pending'），让文档列表/统计可见入库状态
    doc = await document_repo.upsert_by_source(
        session,
        "crawl",
        crawled.id,
        title=crawled.title or crawled.url,
        content=crawled.text_content or "",
        library=task.library,
        version=task.version or "",
        created_by=task.created_by,
        chunk_count=len(crawled.chunks or []),
        metadata_={
            "url": crawled.url,
            "crawl_task_id": crawled.crawl_task_id,
            "depth": crawled.depth,
        },
    )
    # 内容变更导致 Document 回退 pending 时，同步重置 crawled_page，
    # 否则批量入库（get_for_ingest 只取 pending 页）会跳过它
    if doc.ingest_status == "pending":
        crawled.ingest_status = "pending"


async def handle_job_completed(
    session: AsyncSession,
    job_id: str,
    status: str,
    error_message: str | None = None,
) -> CrawlTask | None:
    """处理 job-status-change SSE 事件：更新爬取任务状态。

    返回 task 供调用方（后台订阅器）决定是否触发自动入库。
    """
    task = await crawl_task_repo.find_by_job_id(session, job_id)
    if task is None:
        return None

    if status == "completed":
        await crawl_task_repo.update_status(session, task.id, "crawled")
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
    else:
        return task

    await session.refresh(task)
    return task


async def sync_task_status(
    session: AsyncSession,
    task_id: int,
) -> dict | None:
    """从 docs-mcp REST API 同步任务状态，修正 SSE 丢事件导致的状态偏差。

    返回更新后的序列化任务，若无变化返回 None。
    """
    task = await crawl_task_repo.find_by_id(session, task_id)
    if task is None:
        return None
    if not task.job_id or task.status not in ("crawling", "pending", "failed"):
        return None

    try:
        detail = await docs_mcp_client.get_job_detail(task.job_id)
    except DocsMcpError:
        logger.warning(
            "sync_task_status: failed to fetch job %s from docs-mcp",
            task.job_id,
        )
        return None

    if not isinstance(detail, dict):
        return None

    remote_status = detail.get("status")
    remote_error = detail.get("error")
    remote_error_msg = None
    if isinstance(remote_error, dict):
        remote_error_msg = remote_error.get("message")
    elif isinstance(remote_error, str):
        remote_error_msg = remote_error

    # 状态映射
    local_target = None
    if remote_status == "completed":
        local_target = "crawled"
    elif remote_status == "failed":
        local_target = "failed"
    elif remote_status == "cancelled":
        local_target = "failed"
    else:
        return None

    if local_target == task.status and (
        not remote_error_msg or remote_error_msg == task.error_message
    ):
        return None

    if local_target == "failed":
        await crawl_task_repo.update_status(
            session,
            task.id,
            "failed",
            error_message=remote_error_msg or "docs-mcp job failed",
        )
    else:
        await crawl_task_repo.update_status(session, task.id, local_target)

    await session.refresh(task)
    synced = _serialize_task(task)

    if local_target == "crawled" and task.auto_ingest:
        from tasks.doc_tasks import ingest_crawl_task

        ingest_crawl_task.delay(task.id)
        logger.info("auto ingest dispatched after sync for crawl task %s", task.id)

    return synced


async def ingest_crawl_task(
    session: AsyncSession,
    task_id: int,
) -> dict:
    """批量入库：读 crawled_pages(仅 pending)，按字节分批调 ingest-raw，按批标记。

    按字节分批避免单请求超 docs-mcp bodyLimit(1MB)。
    支持失败重试：只取 ingest_status='pending' 的页，已入库页跳过。
    """
    task = await crawl_task_repo.find_by_id(session, task_id)
    if task is None:
        raise ValueError(f"crawl task {task_id} not found")
    if task.status not in ("crawled", "failed", "ingesting"):
        raise ValueError(f"crawl task status is {task.status}, expected crawled/failed")

    await crawl_task_repo.update_status(session, task_id, "ingesting")
    await session.refresh(task)

    pages = await crawled_page_repo.get_for_ingest(session, task_id)
    if not pages:
        await crawl_task_repo.update_status(session, task_id, "ingested")
        await session.refresh(task)
        return _serialize_task(task)

    try:
        for batch in _chunk_by_bytes(pages, INGEST_BYTE_BUDGET):
            # 页级判重：同 library+version+content_hash 已入库成功 → 标 duplicate，不调 docs-mcp
            to_ingest: list[CrawledPage] = []
            dup_page_ids: list[int] = []
            for p in batch:
                content_hash = hashlib.sha256(
                    (p.text_content or "").encode("utf-8")
                ).hexdigest()
                if await document_repo.find_duplicate_by_hash(
                    session, task.library, task.version or "", content_hash
                ):
                    dup_page_ids.append(p.id)
                else:
                    to_ingest.append(p)

            # 重复页：Document 翻 duplicate，crawled_page 标 duplicate（不再被 get_for_ingest 取）
            for pid in dup_page_ids:
                dup_doc = await document_repo.find_by_source(session, "crawl", pid)
                if dup_doc is not None:
                    await document_repo.update_ingest_status(
                        session, dup_doc.id, "duplicate", chunk_count=0
                    )
            if dup_page_ids:
                await crawled_page_repo.mark_duplicate(session, dup_page_ids)

            # 非重复页：批量入库
            if to_ingest:
                documents = [
                    {
                        "url": p.url,
                        "title": p.title,
                        "contentType": p.content_type or "text/markdown",
                        "content": p.text_content,
                    }
                    for p in to_ingest
                ]
                await docs_mcp_client.ingest_raw(
                    library=task.library,
                    version=task.version or None,
                    documents=documents,
                )
                await crawled_page_repo.mark_ingested(
                    session, [p.id for p in to_ingest]
                )

                # 同步文档记录到平台 DB：翻转 crawl 阶段建立的 pending Document
                for p in to_ingest:
                    existing = await document_repo.find_by_source(
                        session, "crawl", p.id
                    )
                    chunk_count = len(p.chunks or [])
                    if existing is None:
                        # 兜底：crawl 阶段未建 Document（023 之前的旧数据）时补建为 ingested
                        content_hash = hashlib.sha256(
                            (p.text_content or "").encode("utf-8")
                        ).hexdigest()
                        doc = Document(
                            title=p.title or p.url,
                            content=p.text_content or "",
                            library=task.library,
                            version=task.version or "",
                            source_type="crawl",
                            source_id=p.id,
                            chunk_count=chunk_count,
                            ingest_status="ingested",
                            content_hash=content_hash,
                            created_by=task.created_by,
                            metadata_={
                                "url": p.url,
                                "crawl_task_id": p.crawl_task_id,
                                "depth": p.depth,
                            },
                        )
                        await document_repo.create(session, doc)
                    else:
                        await document_repo.update_ingest_status(
                            session, existing.id, "ingested", chunk_count=chunk_count
                        )

            await crawl_task_repo.update_progress(
                session,
                task_id,
                pages_ingested=task.pages_ingested + len(batch),
            )
            await session.refresh(task)

        # 刷新知识库文档计数
        await document_library_service.refresh_document_counts(session, task.library)

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
    await session.execute(delete(CrawlTask).where(CrawlTask.id == task_id))
    await session.flush()
