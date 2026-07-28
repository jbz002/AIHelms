import pytest

from repositories import document_repo
from services import document_service
from services.docs_mcp_client import DocsMcpError, docs_mcp_client


class FakeSession:
    """最小会话：repo 被 monkeypatch 后不实际触碰 DB。"""

    async def refresh(self, obj) -> None:
        pass


@pytest.mark.asyncio
async def test_list_documents_latest_resolves_to_best_version(monkeypatch) -> None:
    async def fake_best(library):
        assert library == "fastapi"
        return {"bestMatch": "2.1.0"}

    captured: dict = {}

    async def fake_count(session, library, source_type, ingest_status, version):
        captured["version"] = version
        return 1

    async def fake_list(
        session, library, source_type, ingest_status, version, page, page_size
    ):
        return []

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    monkeypatch.setattr(document_repo, "count_all", fake_count)
    monkeypatch.setattr(document_repo, "list_all", fake_list)

    await document_service.list_documents(
        FakeSession(), library="fastapi", version="latest"
    )

    assert captured["version"] == "2.1.0"


@pytest.mark.asyncio
async def test_list_documents_concrete_version_not_resolved(monkeypatch) -> None:
    called: list = []

    async def fake_best(library):
        called.append(library)
        return {"bestMatch": "2.1.0"}

    captured: dict = {}

    async def fake_count(session, library, source_type, ingest_status, version):
        captured["version"] = version
        return 0

    async def fake_list(
        session, library, source_type, ingest_status, version, page, page_size
    ):
        return []

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    monkeypatch.setattr(document_repo, "count_all", fake_count)
    monkeypatch.setattr(document_repo, "list_all", fake_list)

    await document_service.list_documents(
        FakeSession(), library="fastapi", version="1.2.3"
    )

    assert called == []  # 具体版本不触发 best 解析
    assert captured["version"] == "1.2.3"


@pytest.mark.asyncio
async def test_list_documents_latest_resolution_failure_falls_back(monkeypatch) -> None:
    async def fake_best(library):
        raise DocsMcpError("boom")

    captured: dict = {}

    async def fake_count(session, library, source_type, ingest_status, version):
        captured["version"] = version
        return 0

    async def fake_list(
        session, library, source_type, ingest_status, version, page, page_size
    ):
        return []

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    monkeypatch.setattr(document_repo, "count_all", fake_count)
    monkeypatch.setattr(document_repo, "list_all", fake_list)

    await document_service.list_documents(
        FakeSession(), library="fastapi", version="latest"
    )

    # 解析失败回退 None（不按版本过滤），避免误命中空版本桶
    assert captured["version"] is None


@pytest.mark.asyncio
async def test_get_ingest_stats_latest_resolves(monkeypatch) -> None:
    async def fake_best(library):
        return {"bestMatch": "3.0.0"}

    captured: dict = {}

    async def fake_grouped(session, library, version):
        captured["version"] = version
        return []

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    monkeypatch.setattr(document_repo, "count_grouped_by_status", fake_grouped)

    await document_service.get_ingest_stats(
        FakeSession(), library="fastapi", version="latest"
    )

    assert captured["version"] == "3.0.0"


@pytest.mark.asyncio
async def test_resolve_version_latest_returns_best_match(monkeypatch) -> None:
    async def fake_best(library):
        return {"bestMatch": "1.2.3", "hasUnversioned": False}

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    assert await docs_mcp_client.resolve_version("lib", "latest") == "1.2.3"


@pytest.mark.asyncio
async def test_resolve_version_latest_only_unversioned_returns_empty(
    monkeypatch,
) -> None:
    async def fake_best(library):
        return {"bestMatch": None, "hasUnversioned": True}

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    # 无 semver 但有 unversioned 桶 → 落 ""（与 search 一致，不再跨版本）
    assert await docs_mcp_client.resolve_version("lib", "latest") == ""


@pytest.mark.asyncio
async def test_resolve_version_latest_empty_library_returns_none(monkeypatch) -> None:
    async def fake_best(library):
        return {"bestMatch": None, "hasUnversioned": False}

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    assert await docs_mcp_client.resolve_version("lib", "latest") is None


@pytest.mark.asyncio
async def test_resolve_version_non_latest_passthrough() -> None:
    assert await docs_mcp_client.resolve_version("lib", "1.0.0") == "1.0.0"
    assert await docs_mcp_client.resolve_version("lib", None) is None
    assert await docs_mcp_client.resolve_version("lib", "") == ""


@pytest.mark.asyncio
async def test_list_documents_latest_only_unversioned_targets_empty_bucket(
    monkeypatch,
) -> None:
    async def fake_best(library):
        return {"bestMatch": None, "hasUnversioned": True}

    captured: dict = {}

    async def fake_count(session, library, source_type, ingest_status, version):
        captured["version"] = version
        return 0

    async def fake_list(
        session, library, source_type, ingest_status, version, page, page_size
    ):
        return []

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    monkeypatch.setattr(document_repo, "count_all", fake_count)
    monkeypatch.setattr(document_repo, "list_all", fake_list)

    await document_service.list_documents(
        FakeSession(), library="lib", version="latest"
    )

    # bestMatch=null + hasUnversioned → 落 unversioned 桶（""），不再跨版本返回
    assert captured["version"] == ""


@pytest.mark.asyncio
async def test_create_crawl_task_latest_resolved_before_enqueue(monkeypatch) -> None:
    from services import crawl_task_service

    captured: dict = {}

    async def fake_best(library):
        return {"bestMatch": "2.0.0", "hasUnversioned": False}

    async def fake_enqueue(library, version, options):
        captured["top_version"] = version
        captured["options_version"] = options.get("version")
        return {"jobId": "job-1"}

    async def fake_create(session, task):
        task.id = 1
        return task

    async def fake_update_status(session, task_id, status):
        pass

    async def fake_ensure(*, session, name, created_by, source_url=None):
        return None

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    monkeypatch.setattr(docs_mcp_client, "enqueue_scrape_job", fake_enqueue)
    monkeypatch.setattr(crawl_task_service.crawl_task_repo, "create", fake_create)
    monkeypatch.setattr(
        crawl_task_service.crawl_task_repo, "update_status", fake_update_status
    )
    monkeypatch.setattr(
        crawl_task_service.document_library_service,
        "ensure_library_exists",
        fake_ensure,
    )

    result = await crawl_task_service.create_crawl_task(
        session=FakeSession(),
        url="http://x",
        library="lib",
        version="latest",
        scraper_options={"url": "http://x", "library": "lib", "version": "latest"},
        created_by=None,
    )

    # latest 在 enqueue 前已解析为最高 semver，顶层 version 与 options.version 同步
    assert captured["top_version"] == "2.0.0"
    assert captured["options_version"] == "2.0.0"
    assert result["version"] == "2.0.0"
