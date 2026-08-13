"""update_document 接口重提编排校验：

- 内容变更 + 已有接口 → 派发提取
- 内容变更 + 无接口 → 不派发（省 token）
- 内容未变 → 不派发
- 派发异常不影响编辑保存

LLM 提取与 Celery 派发依赖真实环境，这里只校验编排（monkeypatch 掉 repo/service）。
"""

import hashlib

import pytest

from repositories import document_api_repo, document_repo
from services import document_api_service, document_service


class FakeSession:
    """最小会话：repo 被 monkeypatch 后不触碰 DB。"""

    async def commit(self) -> None:
        pass

    async def refresh(self, obj) -> None:
        pass


def _fake_doc(content_hash: str = "old", content: str = "hello") -> object:
    return type(
        "D",
        (),
        {
            "id": 7,
            "title": "t",
            "content": content,
            "library": "lib",
            "version": "1.0.0",
            "source_type": "upload",
            "source_id": 1,
            "chunk_count": 0,
            "ingest_status": "ingested",
            "content_hash": content_hash,
            "error_message": None,
            "created_by": 1,
            "metadata_": {},
            "ingest_url": None,
            "created_at": None,
            "updated_at": None,
        },
    )()


def _patch_repo_stubs(monkeypatch, doc) -> dict:
    """patch document_repo 读写桩，返回调用记录。"""

    calls: dict = {}

    async def fake_find(session, document_id):
        calls["found_id"] = document_id
        return doc

    async def fake_update_fields(session, document_id, **kwargs):
        calls["updated_fields"] = kwargs

    async def fake_update_hash(session, document_id, new_hash):
        calls["new_hash"] = new_hash

    async def fake_update_status(session, document_id, status, **kwargs):
        calls["reset_status"] = status

    monkeypatch.setattr(document_repo, "find_by_id", fake_find)
    monkeypatch.setattr(document_repo, "update_document_fields", fake_update_fields)
    monkeypatch.setattr(document_repo, "update_content_hash", fake_update_hash)
    monkeypatch.setattr(document_repo, "update_ingest_status", fake_update_status)
    monkeypatch.setattr(document_service, "_serialize_document", lambda d: {"id": d.id})
    return calls


@pytest.mark.asyncio
async def test_update_content_changed_with_interfaces_triggers_extract(monkeypatch) -> None:
    """内容变更且文档已有接口 → 派发一次提取，传入正确 doc_id 与发起人。"""

    doc = _fake_doc(content_hash="old", content="hello")
    calls = _patch_repo_stubs(monkeypatch, doc)

    async def fake_count(session, document_id):
        return 5  # 已有 5 个接口

    captured = {}

    async def fake_create(session, document_id, current_user):
        captured["args"] = (document_id, current_user)

    monkeypatch.setattr(document_api_repo, "count_by_document", fake_count)
    monkeypatch.setattr(document_api_service, "create_extraction", fake_create)

    await document_service.update_document(
        FakeSession(), 7, content="world", current_user={"id": 42}
    )

    assert calls["reset_status"] == "pending"      # 内容变更重置入库状态
    assert captured["args"] == (7, {"id": 42})     # 派发提取，归属正确


@pytest.mark.asyncio
async def test_update_content_changed_no_interfaces_skips_extract(monkeypatch) -> None:
    """内容变更但文档从未提取过接口 → 不派发（省 token）。"""

    doc = _fake_doc(content_hash="old", content="hello")
    _patch_repo_stubs(monkeypatch, doc)

    async def fake_count(session, document_id):
        return 0  # 无历史接口

    called = False

    async def fake_create(session, document_id, current_user):
        nonlocal called
        called = True

    monkeypatch.setattr(document_api_repo, "count_by_document", fake_count)
    monkeypatch.setattr(document_api_service, "create_extraction", fake_create)

    await document_service.update_document(
        FakeSession(), 7, content="world", current_user={"id": 1}
    )

    assert called is False


@pytest.mark.asyncio
async def test_update_content_unchanged_skips_extract(monkeypatch) -> None:
    """内容 hash 未变 → 既不重置入库也不派发提取。"""

    same_hash = hashlib.sha256("hello".encode("utf-8")).hexdigest()
    doc = _fake_doc(content_hash=same_hash, content="hello")
    calls = _patch_repo_stubs(monkeypatch, doc)

    called = False

    async def fake_create(session, document_id, current_user):
        nonlocal called
        called = True

    monkeypatch.setattr(document_api_service, "create_extraction", fake_create)

    await document_service.update_document(
        FakeSession(), 7, content="hello", current_user={"id": 1}
    )

    assert "reset_status" not in calls   # 未重置入库
    assert called is False               # 未派发


@pytest.mark.asyncio
async def test_extract_failure_does_not_break_save(monkeypatch) -> None:
    """create_extraction 抛异常（如并发冲突）→ 静默吞掉，编辑保存仍成功。"""

    doc = _fake_doc(content_hash="old", content="hello")
    _patch_repo_stubs(monkeypatch, doc)

    async def fake_count(session, document_id):
        return 3

    async def fake_create(session, document_id, current_user):
        raise RuntimeError("busy")

    monkeypatch.setattr(document_api_repo, "count_by_document", fake_count)
    monkeypatch.setattr(document_api_service, "create_extraction", fake_create)

    # 不抛即通过；保存返回正常序列化结果
    result = await document_service.update_document(
        FakeSession(), 7, content="world", current_user={"id": 1}
    )
    assert result == {"id": 7}
