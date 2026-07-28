"""库级批量接口提取编排校验：空库 / 冲突 / 模型不存在。

LLM 提取与 Celery 派发依赖真实环境，留作 dev 手动验证（见 roadmap）。
"""

import pytest

from exceptions import ConflictError, NotFoundError, ValidationError
from repositories import document_api_repo, document_repo, model_repo
from services import document_api_batch_service, document_api_classify_service


class FakeSession:
    """最小会话：repo 被 monkeypatch 后不触碰 DB。"""

    async def commit(self) -> None:
        pass

    async def refresh(self, obj) -> None:
        pass


@pytest.mark.asyncio
async def test_batch_empty_library_raises_validation(monkeypatch) -> None:
    """库无已入库文档 → ValidationError。"""

    async def fake_list(session, statuses, library=None, source_type=None):
        return []

    monkeypatch.setattr(document_repo, "list_by_ingest_status", fake_list)

    with pytest.raises(ValidationError):
        await document_api_batch_service.create_library_extraction(
            FakeSession(), "api", 1, {"id": 1}
        )


@pytest.mark.asyncio
async def test_batch_active_conflict_raises(monkeypatch) -> None:
    """库已有进行中的批量提取任务 → ConflictError。"""

    async def fake_list(session, statuses, library=None, source_type=None):
        return [object()]

    async def fake_active(session, library):
        return object()  # 已有进行中任务

    monkeypatch.setattr(document_repo, "list_by_ingest_status", fake_list)
    monkeypatch.setattr(document_api_repo, "find_active_batch_by_library", fake_active)

    with pytest.raises(ConflictError):
        await document_api_batch_service.create_library_extraction(
            FakeSession(), "api", 1, {"id": 1}
        )


@pytest.mark.asyncio
async def test_batch_model_not_found_raises(monkeypatch) -> None:
    """模型不存在 → NotFoundError。"""

    async def fake_list(session, statuses, library=None, source_type=None):
        return [object()]

    async def fake_active(session, library):
        return None

    async def fake_model(session, mid):
        return None

    monkeypatch.setattr(document_repo, "list_by_ingest_status", fake_list)
    monkeypatch.setattr(document_api_repo, "find_active_batch_by_library", fake_active)
    monkeypatch.setattr(model_repo, "find_by_id", fake_model)

    with pytest.raises(NotFoundError):
        await document_api_batch_service.create_library_extraction(
            FakeSession(), "api", 1, {"id": 1}
        )


@pytest.mark.asyncio
async def test_auto_classify_enqueued_after_batch(monkeypatch) -> None:
    """提取完成后用同模型与发起人派发分类。"""

    captured = {}

    async def fake_create(session, library, mid, user):
        captured["args"] = (library, mid, user)
        return {}

    monkeypatch.setattr(
        document_api_classify_service, "create_classification", fake_create
    )

    job = type(
        "J",
        (),
        {"library": "api", "model_id": 2, "created_by": 9, "total_endpoints": 3},
    )()
    await document_api_batch_service._enqueue_auto_classify(FakeSession(), job)
    assert captured["args"] == ("api", 2, {"id": 9})


@pytest.mark.asyncio
async def test_auto_classify_skipped_on_conflict(monkeypatch) -> None:
    """create_classification 抛 ConflictError → 静默跳过，不传播。"""

    async def fake_create(session, library, mid, user):
        raise ConflictError("busy")

    monkeypatch.setattr(
        document_api_classify_service, "create_classification", fake_create
    )

    job = type(
        "J",
        (),
        {"library": "api", "model_id": 1, "created_by": 1, "total_endpoints": 5},
    )()
    # 不抛即通过
    await document_api_batch_service._enqueue_auto_classify(FakeSession(), job)


def test_should_skip_incremental_hash_match() -> None:
    """已成功提取且 content_hash 相同 → 增量跳过。"""
    latest = type("S", (), {"content_hash": "abc"})()
    assert document_api_batch_service._should_skip_incremental("abc", 3, latest) is True


def test_should_skip_incremental_hash_diff() -> None:
    """文档内容变更（hash 不同）→ 不跳过，需重提。"""
    latest = type("S", (), {"content_hash": "abc"})()
    assert (
        document_api_batch_service._should_skip_incremental("xyz", 3, latest) is False
    )


def test_should_skip_incremental_no_prereqs() -> None:
    """无 content_hash / 无既有接口 / 无成功任务 → 不跳过。"""
    latest = type("S", (), {"content_hash": "abc"})()
    assert document_api_batch_service._should_skip_incremental("", 3, latest) is False
    assert (
        document_api_batch_service._should_skip_incremental("abc", 0, latest) is False
    )
    assert document_api_batch_service._should_skip_incremental("abc", 3, None) is False
