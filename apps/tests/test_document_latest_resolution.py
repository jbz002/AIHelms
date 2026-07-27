import pytest

from repositories import document_repo
from services import document_service
from services.docs_mcp_client import DocsMcpError, docs_mcp_client


class FakeSession:
    """最小会话：repo 被 monkeypatch 后不实际触碰 DB。"""


@pytest.mark.asyncio
async def test_list_documents_latest_resolves_to_best_version(monkeypatch) -> None:
    async def fake_best(library):
        assert library == "fastapi"
        return {"bestMatch": "2.1.0"}

    captured: dict = {}

    async def fake_count(session, library, source_type, ingest_status, version):
        captured["version"] = version
        return 1

    async def fake_list(session, library, source_type, ingest_status, version, page, page_size):
        return []

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    monkeypatch.setattr(document_repo, "count_all", fake_count)
    monkeypatch.setattr(document_repo, "list_all", fake_list)

    await document_service.list_documents(FakeSession(), library="fastapi", version="latest")

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

    async def fake_list(session, library, source_type, ingest_status, version, page, page_size):
        return []

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    monkeypatch.setattr(document_repo, "count_all", fake_count)
    monkeypatch.setattr(document_repo, "list_all", fake_list)

    await document_service.list_documents(FakeSession(), library="fastapi", version="1.2.3")

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

    async def fake_list(session, library, source_type, ingest_status, version, page, page_size):
        return []

    monkeypatch.setattr(docs_mcp_client, "find_best_version", fake_best)
    monkeypatch.setattr(document_repo, "count_all", fake_count)
    monkeypatch.setattr(document_repo, "list_all", fake_list)

    await document_service.list_documents(FakeSession(), library="fastapi", version="latest")

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

    await document_service.get_ingest_stats(FakeSession(), library="fastapi", version="latest")

    assert captured["version"] == "3.0.0"
