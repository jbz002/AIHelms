import pytest

from repositories import (
    crawl_task_repo,
    crawled_page_repo,
    doc_upload_repo,
    document_api_repo,
    document_library_repo,
    document_repo,
)
from services import docs_version_service, document_library_service
from services.docs_mcp_client import docs_mcp_client


class FakeSession:
    """最小会话：repo 全部被 monkeypatch，不触碰真实 DB。"""

    async def commit(self) -> None:
        pass


class FakeLibrary:
    def __init__(self, lib_id: int) -> None:
        self.id = lib_id


VERSION_REPOS = (document_repo, crawled_page_repo, crawl_task_repo, doc_upload_repo)
LIBRARY_REPOS = (document_repo, doc_upload_repo, crawled_page_repo, crawl_task_repo)


@pytest.mark.asyncio
async def test_delete_version_empty_library_force_cleans(monkeypatch) -> None:
    """latest 解析为 None（空壳库/库丢失）→ 不抛 404，直接清平台 DB 库行 + 同步 docs-mcp。"""

    async def fake_resolve(library, version):
        return None

    async def fake_find_by_name(session, name):
        return FakeLibrary(42)

    deleted_library: list = []

    async def fake_delete_library(session, lib_id):
        deleted_library.append(lib_id)

    removed_docs_mcp: list = []

    async def fake_remove_docs_mcp(name):
        removed_docs_mcp.append(name)

    version_deletes: list = []

    async def fake_delete_by_version(session, name, version):
        version_deletes.append(name)

    async def fake_noop_by_library(session, name):
        pass

    async def fake_noop_jobs(session, name):
        pass

    for repo in VERSION_REPOS:
        monkeypatch.setattr(repo, "delete_by_library_version", fake_delete_by_version)
    for repo in LIBRARY_REPOS:
        monkeypatch.setattr(repo, "delete_by_library", fake_noop_by_library)
    monkeypatch.setattr(document_api_repo, "delete_jobs_by_library", fake_noop_jobs)

    monkeypatch.setattr(docs_mcp_client, "resolve_version", fake_resolve)
    monkeypatch.setattr(document_library_repo, "find_by_name", fake_find_by_name)
    monkeypatch.setattr(document_library_repo, "delete_library", fake_delete_library)
    monkeypatch.setattr(
        document_library_service, "remove_docs_mcp_library", fake_remove_docs_mcp
    )

    await docs_version_service.delete_version(FakeSession(), "空壳库", "latest")

    assert deleted_library == [42]
    assert removed_docs_mcp == ["空壳库"]
    assert version_deletes == []


@pytest.mark.asyncio
async def test_delete_version_documents_empty_library_noop(monkeypatch) -> None:
    """latest 解析为 None（空壳库）→ 无版本文档可删，直接成功，不触发版本级删除。"""

    async def fake_resolve(library, version):
        return None

    version_deletes: list = []

    async def fake_delete_by_version(session, name, version):
        version_deletes.append(name)

    for repo in VERSION_REPOS:
        monkeypatch.setattr(repo, "delete_by_library_version", fake_delete_by_version)

    monkeypatch.setattr(docs_mcp_client, "resolve_version", fake_resolve)

    await docs_version_service.delete_version_documents(
        FakeSession(), "空壳库", "latest"
    )

    assert version_deletes == []
