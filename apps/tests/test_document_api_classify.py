"""库级 AI 接口分类编排校验：无接口 / 冲突 / 模型不存在 + 纯函数映射。

LLM 分类与 Celery 派发依赖真实环境，留作 dev 手动验证（见 roadmap）。
"""

import pytest

from exceptions import ConflictError, ValidationError
from repositories import document_api_repo
from services import document_api_classify_service


class FakeSession:
    async def commit(self) -> None:
        pass

    async def refresh(self, obj) -> None:
        pass


@pytest.mark.asyncio
async def test_classify_active_conflict_raises(monkeypatch) -> None:
    """库已有进行中的分类任务 → ConflictError。"""

    async def fake_active(session, library):
        return object()

    monkeypatch.setattr(
        document_api_repo, "find_active_category_by_library", fake_active
    )

    with pytest.raises(ConflictError):
        await document_api_classify_service.create_classification(
            FakeSession(), "api", {"id": 1}
        )


@pytest.mark.asyncio
async def test_classify_no_endpoints_raises_validation(monkeypatch) -> None:
    """库无已提取接口 → ValidationError。"""

    async def fake_active(session, library):
        return None

    async def fake_count(session, library):
        return 0

    monkeypatch.setattr(
        document_api_repo, "find_active_category_by_library", fake_active
    )
    monkeypatch.setattr(document_api_repo, "count_by_library", fake_count)

    with pytest.raises(ValidationError):
        await document_api_classify_service.create_classification(
            FakeSession(), "api", {"id": 1}
        )


def _ep(eid: int):
    return type("E", (), {"id": eid})()


def test_map_categories_by_index() -> None:
    """按 index 映射回 endpoint.id；越界 / 非法序号 / 无序号 忽略。"""
    endpoints = [_ep(10), _ep(20)]
    data = {
        "items": [
            {"index": 0, "category": "用户管理"},
            {"index": 1, "category": "订单管理"},
            {"index": 5, "category": "越界"},
            {"index": "x", "category": "坏序号"},
            {"category": "无序号"},
        ]
    }
    updates = document_api_classify_service._map_categories(data, endpoints)
    assert updates == [(10, "用户管理"), (20, "订单管理")]


def test_collect_categories_dedup_preserves_order() -> None:
    """去重且保留首次出现顺序；空分类名跳过。"""
    data = {
        "items": [
            {"category": "用户管理"},
            {"category": "订单管理"},
            {"category": "用户管理"},
            {"category": ""},
        ]
    }
    cats = document_api_classify_service._collect_categories(data)
    assert cats == ["用户管理", "订单管理"]
