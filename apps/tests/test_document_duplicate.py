"""上传/爬取内容重复检测：标记 duplicate，不向 docs-mcp 重复入库。

docs-mcp 端按 (library, version, url) 覆盖去重，aihelms 按 content_hash 在入库前
预判重，避免把"覆盖性重复 ingest"当新文档计数。
"""

import hashlib

import pytest

from models.db import CrawledPage, CrawlTask, Document, DocUploadRecord
from repositories import (
    crawl_task_repo,
    crawled_page_repo,
    doc_upload_repo,
    document_repo,
)
from services import crawl_task_service, doc_upload_service
from services.docs_mcp_client import DocsMcpError, docs_mcp_client


class _FakeResult:
    """伪查询结果：scalar() 给 advisory lock 用，all() 给 list_urls_by_task 用。"""

    def scalar(self):
        return True

    def all(self):
        return []


class FakeSession:
    """最小会话：repo 被 monkeypatch 后不触碰 DB。"""

    async def refresh(self, obj) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def execute(self, *args, **kwargs):
        # advisory lock（pg_try_advisory_lock）与 list_urls_by_task 走此路径
        return _FakeResult()


async def _async_empty_crawl_results():
    """伪 list_crawl_results：无持久化缓存，回补 no-op。"""
    return {"items": [], "total": 0}


def _make_record(content: str = "abc") -> DocUploadRecord:
    return DocUploadRecord(
        id=1,
        library="api",
        version="1.0.0",
        file_name="a.txt",
        file_size=len(content),
        content_type="text/plain",
        status="pending",
        created_by=None,
        extracted_content=content,
    )


@pytest.mark.asyncio
async def test_upload_duplicate_marks_duplicate_and_skips_ingest(monkeypatch) -> None:
    """同内容已入库成功 → 建 Document(duplicate) + record=duplicate，不调 docs-mcp。"""
    record = _make_record("abc")

    ingest_calls: list = []

    async def fake_ingest_raw(**kwargs):
        ingest_calls.append(kwargs)
        return {"ingested": 1, "chunks": 1}

    upsert_force: list = []

    async def fake_upsert(session, source_type, source_id, **kw):
        upsert_force.append(kw.get("force_status"))
        return None

    record_status: list = []

    async def fake_record_status(session, rid, status, **kw):
        record_status.append(status)

    async def fake_update_extracted(session, rid, content):
        pass

    async def fake_find_dup(session, library, version, content_hash):
        return object()  # 命中：已有同内容 ingested 文档

    monkeypatch.setattr(docs_mcp_client, "ingest_raw", fake_ingest_raw)
    monkeypatch.setattr(document_repo, "upsert_by_source", fake_upsert)
    monkeypatch.setattr(doc_upload_repo, "update_status", fake_record_status)
    monkeypatch.setattr(
        doc_upload_repo, "update_extracted_content", fake_update_extracted
    )
    monkeypatch.setattr(document_repo, "find_duplicate_by_hash", fake_find_dup)

    await doc_upload_service._run_extraction_and_ingest(
        FakeSession(), record, b"abc", auto_ingest=True
    )

    assert ingest_calls == []  # 重复 → 不调 docs-mcp ingest-raw
    assert upsert_force == ["duplicate"]  # Document force_status=duplicate
    assert record_status[-1] == "duplicate"  # DocUploadRecord 标 duplicate


@pytest.mark.asyncio
async def test_upload_non_duplicate_proceeds_without_force_status(monkeypatch) -> None:
    """无重复 → 正常路径建 pending Document（force_status=None）+ ensure_library。"""
    record = _make_record("abc")

    upsert_force: list = []

    async def fake_upsert(session, source_type, source_id, **kw):
        upsert_force.append(kw.get("force_status"))
        return None

    async def fake_find_dup(session, library, version, content_hash):
        return None

    ensure_calls: list = []

    async def fake_ensure(**kw):
        ensure_calls.append(kw)
        return {}

    async def fake_record_status(session, rid, status, **kw):
        pass

    async def fake_update_extracted(session, rid, content):
        pass

    async def fake_split(**kw):
        return {"chunks": 5}

    monkeypatch.setattr(document_repo, "upsert_by_source", fake_upsert)
    monkeypatch.setattr(document_repo, "find_duplicate_by_hash", fake_find_dup)
    monkeypatch.setattr(docs_mcp_client, "ensure_library", fake_ensure)
    monkeypatch.setattr(docs_mcp_client, "split_text", fake_split)
    monkeypatch.setattr(doc_upload_repo, "update_status", fake_record_status)
    monkeypatch.setattr(
        doc_upload_repo, "update_extracted_content", fake_update_extracted
    )

    await doc_upload_service._run_extraction_and_ingest(
        FakeSession(), record, b"abc", auto_ingest=False
    )

    assert upsert_force == [None]  # 非重复 → 默认 pending
    assert len(ensure_calls) == 1  # 走 ensure_library（仅提取模式）


@pytest.mark.asyncio
async def test_crawl_ingest_splits_duplicate_and_new_pages(monkeypatch) -> None:
    """crawl 批量入库：重复页标 duplicate + mark_duplicate，非重复页才调 docs-mcp。"""
    task = CrawlTask(
        id=1,
        library="api",
        version="1.0.0",
        status="crawled",
        pages_ingested=0,
        created_by=None,
    )
    dup_content = "dup content"
    new_content = "new content"
    page_dup = CrawledPage(
        id=1,
        crawl_task_id=1,
        url="http://a",
        title="A",
        text_content=dup_content,
        chunks=[],
        content_type="text/markdown",
    )
    page_new = CrawledPage(
        id=2,
        crawl_task_id=1,
        url="http://b",
        title="B",
        text_content=new_content,
        chunks=[],
        content_type="text/markdown",
    )

    async def fake_find_task(session, tid):
        return task

    async def fake_get_for_ingest(session, tid):
        return [page_dup, page_new]

    status_updates: list = []

    async def fake_task_status(session, tid, status, **kw):
        task.status = status
        status_updates.append(status)

    dup_hash = hashlib.sha256(dup_content.encode("utf-8")).hexdigest()

    async def fake_find_dup(session, library, version, content_hash):
        return object() if content_hash == dup_hash else None

    async def fake_find_source(session, st, sid):
        return Document(id=sid, ingest_status="pending", chunk_count=0)

    doc_status: list = []

    async def fake_update_doc(session, did, status, **kw):
        doc_status.append((did, status))

    mark_dup: list = []

    async def fake_mark_dup(session, ids):
        mark_dup.extend(ids)

    mark_ing: list = []

    async def fake_mark_ing(session, ids):
        mark_ing.extend(ids)

    ingest_docs: list = []

    async def fake_ingest_raw(**kw):
        ingest_docs.append(kw.get("documents"))
        return {"ingested": 1}

    async def fake_progress(session, tid, **kw):
        pass

    async def fake_refresh_counts(session, lib):
        pass

    monkeypatch.setattr(crawl_task_repo, "find_by_id", fake_find_task)
    monkeypatch.setattr(crawl_task_repo, "update_status", fake_task_status)
    monkeypatch.setattr(crawl_task_repo, "update_progress", fake_progress)
    monkeypatch.setattr(crawled_page_repo, "get_for_ingest", fake_get_for_ingest)
    monkeypatch.setattr(crawled_page_repo, "mark_duplicate", fake_mark_dup)
    monkeypatch.setattr(crawled_page_repo, "mark_ingested", fake_mark_ing)
    monkeypatch.setattr(document_repo, "find_duplicate_by_hash", fake_find_dup)
    monkeypatch.setattr(document_repo, "find_by_source", fake_find_source)
    monkeypatch.setattr(document_repo, "update_ingest_status", fake_update_doc)
    monkeypatch.setattr(docs_mcp_client, "ingest_raw", fake_ingest_raw)
    monkeypatch.setattr(
        crawl_task_service.document_library_service,
        "refresh_document_counts",
        fake_refresh_counts,
    )
    # 入库前 REST 回补：docs-mcp 无持久化缓存 → 返回空，回补 no-op
    monkeypatch.setattr(
        docs_mcp_client,
        "list_crawl_results",
        lambda *a, **k: _async_empty_crawl_results(),
    )

    await crawl_task_service.ingest_crawl_task(FakeSession(), 1)

    assert mark_dup == [1]  # 重复页标 duplicate
    assert (1, "duplicate") in doc_status
    assert mark_ing == [2]  # 非重复页入库
    assert (2, "ingested") in doc_status
    # ingest_raw 只收到非重复页
    assert len(ingest_docs) == 1
    assert [d["url"] for d in ingest_docs[0]] == ["http://b"]
    assert "ingested" in status_updates


@pytest.mark.asyncio
async def test_create_crawl_task_rejects_active_duplicate(monkeypatch) -> None:
    """同 (library, version) 已有 active 任务 → 抛 CrawlTaskConflictError，不 enqueue。"""

    class _ActivePresent:
        def scalar_one(self) -> int:
            return 1  # 已有 1 个 active crawl task

    session = FakeSession()

    async def fake_execute(*args, **kwargs):
        return _ActivePresent()

    session.execute = fake_execute  # type: ignore[method-assign]

    enqueue_calls: list = []

    async def fake_enqueue(**kwargs):
        enqueue_calls.append(kwargs)
        return {"jobId": "j1"}

    monkeypatch.setattr(docs_mcp_client, "enqueue_scrape_job", fake_enqueue)

    with pytest.raises(crawl_task_service.CrawlTaskConflictError):
        await crawl_task_service.create_crawl_task(
            session=session,
            url="http://a",
            library="api",
            version="1.0.0",
            scraper_options={},
            created_by=None,
        )
    assert enqueue_calls == []  # 拒绝创建,未 enqueue docs-mcp job


@pytest.mark.asyncio
async def test_sync_404_salvages_when_pages_exist(monkeypatch) -> None:
    """docs-mcp job 404 但 crawl_results 有页 → salvage 置 crawled 触发 ingest,不标 failed。"""
    task = CrawlTask(
        id=5,
        library="api",
        version="1.0.0",
        status="crawling",
        job_id="gone-job",
        auto_ingest=True,
        pages_crawled=0,
        created_by=None,
    )

    async def fake_find(session, tid):
        return task

    async def fake_get_job_detail(job_id):
        raise DocsMcpError("not found", status_code=404)

    backfill_called: list = []

    async def fake_backfill(session, t):
        t.pages_crawled = 3  # salvage 到 3 页
        backfill_called.append(t.id)

    status_updates: list = []

    async def fake_update_status(session, tid, status, **kw):
        task.status = status
        status_updates.append(status)

    dispatched: list = []

    class _FakeDelay:
        def delay(self, tid):
            dispatched.append(tid)

    import tasks.doc_tasks as doc_tasks_mod

    monkeypatch.setattr(crawl_task_repo, "find_by_id", fake_find)
    monkeypatch.setattr(docs_mcp_client, "get_job_detail", fake_get_job_detail)
    monkeypatch.setattr(
        crawl_task_service, "_backfill_pages_from_docs_mcp", fake_backfill
    )
    monkeypatch.setattr(crawl_task_repo, "update_status", fake_update_status)
    monkeypatch.setattr(doc_tasks_mod, "ingest_crawl_task", _FakeDelay())

    result = await crawl_task_service.sync_task_status(FakeSession(), 5)

    assert backfill_called == [5]
    assert "crawled" in status_updates
    assert "failed" not in status_updates
    assert dispatched == [5]  # auto_ingest → 救回后触发入库
    assert result is not None


@pytest.mark.asyncio
async def test_sync_404_fails_and_clears_when_no_salvage(monkeypatch) -> None:
    """docs-mcp job 404 且 crawl_results 无页 → 标 failed + 清理 docs-mcp 悬空 crawl_results。"""
    task = CrawlTask(
        id=6,
        library="api",
        version="1.0.0",
        status="crawling",
        job_id="gone-job",
        auto_ingest=False,
        pages_crawled=0,
        created_by=None,
    )

    async def fake_find(session, tid):
        return task

    async def fake_get_job_detail(job_id):
        raise DocsMcpError("not found", status_code=404)

    async def fake_backfill(session, t):
        # salvage 不到任何页,pages_crawled 仍 0
        return None

    status_updates: list = []

    async def fake_update_status(session, tid, status, **kw):
        task.status = status
        status_updates.append(status)

    clear_calls: list = []

    async def fake_clear(library, version):
        clear_calls.append((library, version))

    monkeypatch.setattr(crawl_task_repo, "find_by_id", fake_find)
    monkeypatch.setattr(docs_mcp_client, "get_job_detail", fake_get_job_detail)
    monkeypatch.setattr(
        crawl_task_service, "_backfill_pages_from_docs_mcp", fake_backfill
    )
    monkeypatch.setattr(crawl_task_repo, "update_status", fake_update_status)
    monkeypatch.setattr(docs_mcp_client, "clear_crawl_results", fake_clear)

    result = await crawl_task_service.sync_task_status(FakeSession(), 6)

    assert "failed" in status_updates
    assert clear_calls == [("api", "1.0.0")]  # 清理 docs-mcp 悬空缓存
    assert result is not None
