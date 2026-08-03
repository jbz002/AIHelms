"""爬取任务服务：crawl-only 模式的任务管理、页面收集、批量入库。"""

import hashlib
import logging

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import CrawledPage, CrawlTask, Document
from repositories import crawl_task_repo, crawled_page_repo, document_repo
from services import document_library_service
from services.docs_mcp_client import DocsMcpError, docs_mcp_client
from services.document_service import build_ingest_url

logger = logging.getLogger(__name__)


class CrawlTaskConflictError(Exception):
    """同 (library, version) 已有进行中的爬取任务时抛出，路由层转 409。"""


# docs-mcp Fastify 默认 bodyLimit 1MB，留半给 JSON/url/title 开销
INGEST_BYTE_BUDGET = 512 * 1024
# 单批文档数上限：docs-mcp 顺序 embedding，小页扎堆成一批会撞超时（即使字节未超）
MAX_BATCH_DOCS = 5


def _chunk_by_bytes(
    pages: list[CrawledPage], budget: int, max_docs: int
) -> list[list[CrawledPage]]:
    """按累计字节 + 文档数双限切批。

    单批 ≤ budget 字节且 ≤ max_docs 页；单页超 budget 自成一批。
    双限避免小页扎堆成一批，导致 docs-mcp 顺序 embedding 超时。
    """
    batches: list[list[CrawledPage]] = []
    batch: list[CrawledPage] = []
    size = 0
    for p in pages:
        psize = len((p.text_content or "").encode("utf-8"))
        if batch and (size + psize > budget or len(batch) >= max_docs):
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
        "is_partial": (task.pages_backfilled or 0) > 0 or (task.pages_empty or 0) > 0,
        "pages_backfilled": task.pages_backfilled or 0,
        "pages_empty": task.pages_empty or 0,
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

    # 同 (library, version) 已有进行中的爬取任务则拒绝:crawl_results 按 (version_id,
    # url) 唯一无 job_id 隔离,并发爬会互相覆盖污染(新任务 clearCrawlResults 清掉旧任务
    # 正在回补的缓存)。ingested/failed/crawled 稳态不阻断(增量/重爬)。
    active = await session.execute(
        select(func.count())
        .select_from(CrawlTask)
        .where(
            func.lower(CrawlTask.library) == library.lower(),
            CrawlTask.version == (version or ""),
            CrawlTask.status.in_(["pending", "crawling", "ingesting"]),
        )
    )
    if active.scalar_one() > 0:
        raise CrawlTaskConflictError(
            "该版本已有进行中的爬取任务，请等待完成或删除后再试"
        )

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
        ingest_url=build_ingest_url("crawl", crawled.id, {"url": crawled.url}),
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
    except DocsMcpError as e:
        # 404 = docs-mcp 已无此 job（job_id 仅内存，服务重启后旧 id 失效）。
        # 任务成孤儿：标 failed 并给可操作提示，避免永久卡在 crawling/pending。
        if e.status_code == 404:
            # docs-mcp 重启后旧 job_id 仅内存态丢失,但 crawl_results 是持久化的。
            # 先尝试从 crawl_results salvage:有页则救回(置 crawled 触发 ingest),
            # 无页才判废,并清理 docs-mcp 侧悬空 crawl_results(防长期累积)。
            await _backfill_pages_from_docs_mcp(session, task)
            await session.refresh(task)
            if (task.pages_crawled or 0) > 0:
                await crawl_task_repo.update_status(
                    session, task.id, "crawled", error_message=None
                )
                await session.refresh(task)
                logger.info(
                    "sync_task_status: job %s gone (404), task %s salvaged %d pages",
                    task.job_id,
                    task.id,
                    task.pages_crawled,
                )
                synced = _serialize_task(task)
                if task.auto_ingest:
                    from tasks.doc_tasks import ingest_crawl_task

                    ingest_crawl_task.delay(task.id)
                return synced
            await crawl_task_repo.update_status(
                session,
                task.id,
                "failed",
                error_message="docs-mcp 任务已丢失（服务可能重启），请重新爬取",
            )
            await session.refresh(task)
            try:
                await docs_mcp_client.clear_crawl_results(
                    task.library, task.version or None
                )
            except DocsMcpError:
                logger.warning(
                    "sync_task_status: clear crawl_results failed for task %s",
                    task.id,
                )
            logger.info(
                "sync_task_status: job %s gone (404), task %s -> failed (no salvage)",
                task.job_id,
                task.id,
            )
            return _serialize_task(task)
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


async def reconcile_stale_tasks(session: AsyncSession) -> None:
    """周期兜底（celery beat 驱动），自愈 SSE/进程中断导致的卡死任务。

    - crawling/pending 卡死 → sync_task_status（含 job 404 标孤儿 failed）；
      若远程 completed 且 auto_ingest，sync 内部会触发入库。
    - ingesting 卡死（celery worker 已死）→ 重新触发 ingest_crawl_task（幂等可重入，
      advisory lock 防双跑）。

    阈值：crawling 3min、pending 5min、ingesting 10min（大于单批 180s 超时，避免误杀在跑入库）。
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from tasks.doc_tasks import ingest_crawl_task

    now = datetime.now(timezone.utc)
    crawling_cutoff = now - timedelta(minutes=3)
    pending_cutoff = now - timedelta(minutes=5)
    ingesting_cutoff = now - timedelta(minutes=10)

    # crawling 卡死：job_id 非空 + started_at 早于 3min 前
    result = await session.execute(
        select(CrawlTask).where(
            CrawlTask.status == "crawling",
            CrawlTask.job_id != "",
            CrawlTask.started_at.isnot(None),
            CrawlTask.started_at < crawling_cutoff,
        )
    )
    for task in result.scalars().all():
        try:
            await sync_task_status(session, task.id)
        except Exception:
            logger.debug(
                "reconcile: sync crawling task %s failed", task.id, exc_info=True
            )

    # pending 卡死：created_at 早于 5min 前
    result = await session.execute(
        select(CrawlTask).where(
            CrawlTask.status == "pending",
            CrawlTask.job_id != "",
            CrawlTask.created_at < pending_cutoff,
        )
    )
    for task in result.scalars().all():
        try:
            await sync_task_status(session, task.id)
        except Exception:
            logger.debug(
                "reconcile: sync pending task %s failed", task.id, exc_info=True
            )

    # ingesting 卡死：started_at 早于 10min 前 → 重新触发入库
    result = await session.execute(
        select(CrawlTask).where(
            CrawlTask.status == "ingesting",
            CrawlTask.started_at.isnot(None),
            CrawlTask.started_at < ingesting_cutoff,
        )
    )
    for task in result.scalars().all():
        logger.info("reconcile: re-trigger ingest for stale ingesting task %s", task.id)
        ingest_crawl_task.delay(task.id)

    # crawled 卡死:auto_ingest=true 但 dispatch 失败(Celery broker 丢任务),任务永久卡
    # crawled。finished_at 早于 5min 前则重 dispatch(幂等+锁)。auto_ingest=false 不动
    # (设计内等待手动入库)。
    crawled_cutoff = now - timedelta(minutes=5)
    result = await session.execute(
        select(CrawlTask).where(
            CrawlTask.status == "crawled",
            CrawlTask.auto_ingest.is_(True),
            CrawlTask.finished_at.isnot(None),
            CrawlTask.finished_at < crawled_cutoff,
        )
    )
    for task in result.scalars().all():
        logger.info("reconcile: re-trigger ingest for stale crawled task %s", task.id)
        ingest_crawl_task.delay(task.id)


async def _backfill_pages_from_docs_mcp(session: AsyncSession, task: CrawlTask) -> None:
    """从 docs-mcp crawl_results 回补 SSE 断连期间丢失的页面。

    crawlOnly 模式下 docs-mcp 持久化了全部抓取页原文（SSE 仅作实时进度）。
    入库前以 (library, version) 为权威源，把本地 crawled_pages 缺失的 url 补齐为
    pending，使 get_for_ingest 取到完整页集合。仅补缺失 url，不覆盖已存在页
    （避免重置已 ingested 页状态）。docs-mcp 不可达时静默跳过，不阻断入库。
    """
    existing_urls = await crawled_page_repo.list_urls_by_task(session, task.id)
    backfilled = 0
    page_no = 1
    while True:
        try:
            result = await docs_mcp_client.list_crawl_results(
                task.library, task.version or None, page=page_no, page_size=100
            )
        except DocsMcpError as e:
            logger.warning("backfill crawl_results failed: %s", str(e))
            return
        if not isinstance(result, dict):
            return
        items = result.get("items") or []
        if not items:
            break
        for item in items:
            url = item.get("url") or ""
            if not url or url in existing_urls:
                continue
            await crawled_page_repo.upsert_by_task_url(
                session,
                crawl_task_id=task.id,
                url=url,
                title=item.get("title") or "",
                source_content_type=item.get("contentType") or "",
                content_type=item.get("contentType") or "",
                text_content=item.get("textContent") or "",
                links=[],
                chunks=[],
                depth=item.get("depth") or 0,
            )
            existing_urls.add(url)
            backfilled += 1
        total = result.get("total", 0) or 0
        if page_no * 100 >= total:
            break
        page_no += 1

    # 回补后 pages_crawled 反映真实抓取页数（SSE + REST）；
    # pages_backfilled 累计本次回补数，作为 is_partial 的真信号（SSE 中断过）
    if backfilled:
        await crawl_task_repo.update_progress(
            session,
            task.id,
            pages_crawled=len(existing_urls),
            pages_backfilled=(task.pages_backfilled or 0) + backfilled,
        )


async def ingest_crawl_task(
    session: AsyncSession,
    task_id: int,
) -> dict:
    """批量入库：读 crawled_pages(仅 pending)，按字节分批调 ingest-raw，按批标记。

    按字节分批避免单请求超 docs-mcp bodyLimit(1MB)。
    支持失败重试：只取 ingest_status='pending' 的页，已入库页跳过。
    入库前从 docs-mcp crawl_results 回补 SSE 期间丢失的页（页级恢复）。

    分阶段提交：进入 ingesting / 每批入库后各 commit 一次，让前端轮询能见到
    `ingesting` 态与 `pages_ingested` 进度（否则 Celery 单事务全程不提交，前端
    从 crawled 直跳 ingested）。为此 advisory lock 改 session 级（跨 commit 保持）。
    """
    task = await crawl_task_repo.find_by_id(session, task_id)
    if task is None:
        raise ValueError(f"crawl task {task_id} not found")
    if task.status not in ("crawled", "failed", "ingesting"):
        raise ValueError(f"crawl task status is {task.status}, expected crawled/failed")

    # session 级 advisory lock：防止 beat 重触发与手动重触发并发双跑（ingest 幂等可重入，
    # 但双跑会重复向量化、progress 双计）。改用 session 级（非事务级），跨分阶段 commit
    # 保持，finally 显式释放，进程崩溃由 PG 连接断开自动释放。
    lock_key = 91020250700 + task_id
    got_lock = (
        await session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key})
    ).scalar()
    if not got_lock:
        logger.info(
            "ingest_crawl_task: task %s already running (lock held), skip", task_id
        )
        return _serialize_task(task)

    try:
        # 1) 置 ingesting 并立即提交：前端轮询马上能见到「入库中」
        await crawl_task_repo.update_status(
            session, task_id, "ingesting", error_message=None
        )
        await session.commit()
        await session.refresh(task)

        # 2) 入库前从 docs-mcp 权威源回补 SSE 断连期间丢失的页（页级恢复核心）
        await _backfill_pages_from_docs_mcp(session, task)
        await session.commit()
        await session.refresh(task)

        pages = await crawled_page_repo.get_for_ingest(session, task_id)
        if not pages:
            await crawl_task_repo.update_status(session, task_id, "ingested")
            await session.commit()
            await session.refresh(task)
            return _serialize_task(task)

        for batch in _chunk_by_bytes(pages, INGEST_BYTE_BUDGET, MAX_BATCH_DOCS):
            # 页级分类：空内容 / 重复 / 待入库
            to_ingest: list[CrawledPage] = []
            dup_page_ids: list[int] = []
            empty_page_ids: list[int] = []
            for p in batch:
                if not (p.text_content or "").strip():
                    empty_page_ids.append(p.id)
                    continue
                content_hash = hashlib.sha256(
                    (p.text_content or "").encode("utf-8")
                ).hexdigest()
                if await document_repo.find_duplicate_by_hash(
                    session, task.library, task.version or "", content_hash
                ):
                    dup_page_ids.append(p.id)
                else:
                    to_ingest.append(p)

            # 空内容页：docs-mcp addDocuments 对 0 chunks 直接 return 不写向量，
            # 如实标 failed(chunk_count=0)，不调 docs-mcp，避免双边「是否真入库」不一致
            for pid in empty_page_ids:
                empty_doc = await document_repo.find_by_source(session, "crawl", pid)
                if empty_doc is not None:
                    await document_repo.update_ingest_status(
                        session, empty_doc.id, "failed", chunk_count=0
                    )
            if empty_page_ids:
                await crawled_page_repo.mark_failed(session, empty_page_ids)

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
                        "url": build_ingest_url("crawl", p.id, {"url": p.url}),
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
                            ingest_url=build_ingest_url("crawl", p.id, {"url": p.url}),
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

            # 每批提交一次：前端轮询可见 pages_ingested 进度增长；
            # pages_empty 累计空内容页数，作为 is_partial 的真信号（内容缺失）
            await crawl_task_repo.update_progress(
                session,
                task_id,
                pages_ingested=task.pages_ingested + len(batch),
                pages_empty=(task.pages_empty or 0) + len(empty_page_ids),
            )
            await session.commit()
            await session.refresh(task)

        # 刷新知识库文档计数
        await document_library_service.refresh_document_counts(session, task.library)

        await crawl_task_repo.update_status(session, task_id, "ingested")
        await session.commit()
        await session.refresh(task)
        return _serialize_task(task)

    except DocsMcpError as e:
        logger.error("ingest crawl task failed: %s", str(e))
        await crawl_task_repo.update_status(
            session, task_id, "failed", error_message=str(e)[:500]
        )
        await session.commit()
        await session.refresh(task)
        return _serialize_task(task)
    finally:
        # 释放 session 级 advisory lock（连接断开也会自动释放，此处显式提前释放）
        try:
            await session.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key}
            )
        except Exception:
            logger.debug(
                "ingest_crawl_task unlock failed: task %s", task_id, exc_info=True
            )


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
    task = await crawl_task_repo.find_by_id(session, task_id)
    # 删除 crawling/pending 中的任务前,best-effort 取消 docs-mcp 端 job,避免孤儿 job
    # 持续抓取、SSE 推送被丢弃、资源泄漏。ingesting 阶段 docs-mcp job 已结束,无需 cancel。
    if task and task.job_id and task.status in ("pending", "crawling"):
        try:
            await docs_mcp_client.cancel_job(task.job_id)
        except DocsMcpError:
            logger.warning(
                "delete_crawl_task: cancel job %s failed, proceed to delete",
                task.job_id,
                exc_info=True,
            )
    await crawled_page_repo.delete_by_task_id(session, task_id)
    await session.execute(delete(CrawlTask).where(CrawlTask.id == task_id))
    await session.flush()
