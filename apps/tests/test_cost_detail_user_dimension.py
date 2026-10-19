from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

# 先导入触发 services 包完整初始化，绕开 export_task_builders 的既有循环导入
from api.v1 import efficiency as efficiency_api  # noqa: F401
from repositories import efficiency_cost_repo, efficiency_model_stats_repo
from services import efficiency_cost_service


def _mock_session(rows: list[tuple]) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_build_cost_filters_appends_user_filter_when_set():
    filters, params = efficiency_cost_repo._build_cost_filters(
        date(2026, 10, 1), date(2026, 10, 31), None, None, "c", None, user_id=7
    )

    assert "c.user_id = :filter_user_id" in filters
    assert params["filter_user_id"] == 7


@pytest.mark.asyncio
async def test_build_cost_filters_omits_user_filter_when_none():
    filters, params = efficiency_cost_repo._build_cost_filters(
        date(2026, 10, 1), date(2026, 10, 31), None, None, "c", None
    )

    assert "filter_user_id" not in filters
    assert "filter_user_id" not in params


@pytest.mark.asyncio
async def test_cost_detail_by_model_forwards_user_filter():
    session = _mock_session([])

    await efficiency_cost_repo.get_cost_detail_by_model(
        session, date(2026, 10, 1), date(2026, 10, 31), None, None, None, user_id=7
    )

    params = session.execute.await_args.args[1]
    assert params["filter_user_id"] == 7


@pytest.mark.asyncio
async def test_cost_detail_by_user_returns_rows_without_top10_limit():
    row = (
        7,
        "Alice",
        "技术中心",
        12.0,
        2.0,
        14.0,
        10.0,
        30,
        29,
        100,
        200,
        5,
        8,
        95,
    )
    session = _mock_session([row])

    rows = await efficiency_model_stats_repo.get_cost_detail_by_user(
        session, date(2026, 10, 1), date(2026, 10, 31)
    )

    sql = str(session.execute.await_args.args[0])
    assert "LIMIT 10" not in sql
    assert "c.user_id IS NOT NULL" in sql
    assert rows == [
        {
            "user_id": 7,
            "user_name": "Alice",
            "department": "技术中心",
            "llm_cost": 12.0,
            "mcp_cost": 2.0,
            "internal_cost": 14.0,
            "external_cost": 10.0,
            "cost_diff": 4.0,
            "requests": 30,
            "successful_requests": 29,
            "input_tokens": 100,
            "output_tokens": 200,
            "cache_read_tokens": 5,
            "cache_creation_tokens": 8,
            "fresh_input_tokens": 95,
        }
    ]


@pytest.mark.asyncio
async def test_get_cost_detail_user_tab_returns_user_key(monkeypatch):
    user_rows = [
        {
            "user_id": 7,
            "user_name": "Alice",
            "department": "技术中心",
            "llm_cost": 12.0,
            "mcp_cost": 2.0,
            "internal_cost": 14.0,
            "external_cost": 10.0,
            "cost_diff": 4.0,
            "requests": 30,
            "successful_requests": 29,
            "input_tokens": 100,
            "output_tokens": 200,
            "cache_read_tokens": 5,
            "cache_creation_tokens": 8,
            "fresh_input_tokens": 95,
        }
    ]
    monkeypatch.setattr(
        efficiency_model_stats_repo,
        "get_cost_detail_by_user",
        AsyncMock(return_value=user_rows),
    )

    data = await efficiency_cost_service.get_cost_detail(
        object(), date(2026, 10, 1), date(2026, 10, 31), tab="user"
    )

    assert data == {"user": user_rows}


@pytest.mark.asyncio
async def test_get_cost_detail_model_tab_forwards_user_id(monkeypatch):
    call = AsyncMock(return_value=[])
    monkeypatch.setattr(efficiency_cost_repo, "get_cost_detail_by_model", call)

    await efficiency_cost_service.get_cost_detail(
        object(),
        date(2026, 10, 1),
        date(2026, 10, 31),
        tab="model",
        user_id=7,
    )

    assert call.await_args.args[6] == 7


@pytest.mark.asyncio
async def test_export_cost_user_tab_builds_rows(monkeypatch):
    from services import export_task_builders

    detail = {
        "user": [
            {
                "user_id": 7,
                "user_name": "Alice",
                "department": "技术中心",
                "llm_cost": 12.0,
                "mcp_cost": 2.0,
                "internal_cost": 14.0,
                "external_cost": 10.0,
                "cost_diff": 4.0,
                "requests": 30,
                "successful_requests": 29,
                "input_tokens": 100,
                "output_tokens": 200,
                "cache_read_tokens": 5,
                "cache_creation_tokens": 8,
                "fresh_input_tokens": 95,
            }
        ]
    }
    service_call = AsyncMock(return_value=detail)
    monkeypatch.setattr(
        efficiency_cost_service, "get_cost_detail", service_call
    )

    header, rows = await export_task_builders._build_efficiency_rows(
        object(),
        "cost_user",
        {
            "dimension": "department",
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
        },
    )

    assert header[0] == "姓名"
    assert header[-1] == "真实消耗Token"
    assert len(header) == len(rows[0])
    # 真实消耗 = 新增输入95 + 输出200 + 缓存写8 + 缓存读5
    assert rows[0][-1] == 95 + 200 + 8 + 5
    assert service_call.await_args.args[8] is None
