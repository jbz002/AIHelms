from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.v1 import efficiency as efficiency_api
from repositories import efficiency_model_stats_repo
from services import efficiency_model_stats_service


def _mock_session(rows: list[tuple]) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_model_summary_sql_normalizes_fresh_input_and_filters_llm():
    session = _mock_session(
        [
            (
                "openai/deepseek-v4.1-flash",
                "DeepSeek V4.1 Flash",
                "deepseek-v4.1-flash",
                100,
                98,
                1000,
                200,
                300,
                50,
                700,
                12.5,
                45000,
            )
        ]
    )

    rows = await efficiency_model_stats_repo.get_user_model_summary(
        session, date(2026, 10, 1), date(2026, 10, 31), 7
    )

    sql = str(session.execute.await_args.args[0])
    params = session.execute.await_args.args[1]
    assert "GREATEST(c.input_tokens - c.cache_read_tokens, 0)" in sql
    assert "cost_type = 'llm'" in sql
    assert "c.user_id = :user_id" in sql
    assert params == {
        "user_id": 7,
        "start": date(2026, 10, 1),
        "end": date(2026, 10, 31),
    }
    assert rows[0]["fresh_input_tokens"] == 700
    assert rows[0]["request_count"] == 100


@pytest.mark.asyncio
async def test_model_latency_sql_uses_percentile_and_speed_filter():
    session = _mock_session([("m1", 3000, 12000, 10, 620.0)])

    rows = await efficiency_model_stats_repo.get_user_model_latency(
        session, date(2026, 10, 1), date(2026, 10, 31), 7
    )

    sql = str(session.execute.await_args.args[0])
    assert "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ttft_ms)" in sql
    assert "duration_ms > ttft_ms" in sql
    assert "ttft_ms IS NOT NULL" in sql
    assert "status = 'success'" in sql
    assert rows == [
        {
            "model": "m1",
            "speed_output_tokens": 3000,
            "speed_decode_ms": 12000,
            "speed_samples": 10,
            "first_token_ms": 620.0,
        }
    ]


def _summary_row(**overrides):
    row = {
        "model": "m1",
        "platform_model_name": "M1",
        "platform_model_id": "m1",
        "request_count": 100,
        "successful_requests": 98,
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_tokens": 300,
        "cache_creation_tokens": 50,
        "fresh_input_tokens": 700,
        "internal_cost": 12.5,
        "total_duration_ms": 45000,
    }
    row.update(overrides)
    return row


def test_merge_rows_derives_cc_switch_metrics():
    latency = [
        {
            "model": "m1",
            "speed_output_tokens": 3000,
            "speed_decode_ms": 12000,
            "speed_samples": 10,
            "first_token_ms": 620.0,
        }
    ]

    items = efficiency_model_stats_service._merge_rows([_summary_row()], latency)

    item = items[0]
    # 真实消耗 = 新增输入700 + 输出200 + 缓存写入50 + 缓存命中300
    assert item["real_total_tokens"] == 1250
    # 缓存命中率 = 300 / (700 + 50 + 300)，分母不含输出
    assert item["cache_hit_rate"] == round(300 / 1050 * 100, 1)
    assert item["success_rate"] == 98.0
    assert item["avg_cost_per_request"] == 0.125
    assert item["avg_latency_ms"] == round(45000 / 98, 1)
    assert item["speed_tokens_per_sec"] == 250.0
    assert item["first_token_ms"] == 620.0


def test_merge_rows_speed_null_when_no_eligible_samples():
    items = efficiency_model_stats_service._merge_rows([_summary_row()], [])

    item = items[0]
    assert item["speed_tokens_per_sec"] is None
    assert item["first_token_ms"] is None
    assert item["speed_sample_count"] == 0


def test_merge_rows_zero_decode_ms_yields_null_speed():
    latency = [
        {
            "model": "m1",
            "speed_output_tokens": 0,
            "speed_decode_ms": 0,
            "speed_samples": 0,
            "first_token_ms": None,
        }
    ]

    items = efficiency_model_stats_service._merge_rows([_summary_row()], latency)

    assert items[0]["speed_tokens_per_sec"] is None


def test_merge_rows_zero_cacheable_yields_null_hit_rate():
    row = _summary_row(
        input_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        fresh_input_tokens=0,
    )

    items = efficiency_model_stats_service._merge_rows([row], [])

    assert items[0]["cache_hit_rate"] is None


@pytest.mark.asyncio
async def test_get_user_model_stats_merges_repo_results(monkeypatch):
    monkeypatch.setattr(
        efficiency_model_stats_repo,
        "get_user_model_summary",
        AsyncMock(return_value=[_summary_row()]),
    )
    monkeypatch.setattr(
        efficiency_model_stats_repo,
        "get_user_model_latency",
        AsyncMock(return_value=[]),
    )

    data = await efficiency_model_stats_service.get_user_model_stats(
        object(), date(2026, 10, 1), date(2026, 10, 31), 7
    )

    assert data["items"][0]["model"] == "m1"
    assert data["items"][0]["real_total_tokens"] == 1250


@pytest.mark.asyncio
async def test_api_model_stats_rejects_non_self_scope():
    with pytest.raises(Exception) as exc_info:
        await efficiency_api.get_model_stats(
            None, date(2026, 10, 1), date(2026, 10, 31), "team", object(), {"id": 1}
        )
    assert exc_info.value.status_code == 403
