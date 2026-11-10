"""P1 网关稳定性回归：辅助端点、媒体剥离、流式超时、健康可见性与探针。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from services import access_cache_probe, access_history_probe, model_service

ROOT = Path(__file__).resolve().parents[2]


def test_gateway_rewrites_auxiliary_endpoints_and_strips_media():
    lua = (ROOT / "docker" / "openresty" / "model_rewrite.lua").read_text(
        encoding="utf-8"
    )
    assert "/v1/messages/count_tokens" in lua
    assert "/v1/responses/compact" in lua
    assert "ONE_M_CONTEXT_MARKER" in lua
    for media_type in ("input_audio", "document", "input_file", "input_image"):
        assert media_type in lua

    for conf_name in ("nginx.conf", "nginx.prod.conf"):
        conf = (ROOT / "docker" / "openresty" / conf_name).read_text(encoding="utf-8")
        assert "messages/count_tokens" in conf
        assert "responses/compact" in conf


def test_router_payload_includes_stream_timeout():
    settings = SimpleNamespace(
        routing_strategy="simple-shuffle",
        allowed_fails=3,
        cooldown_time=60,
        num_retries=2,
        timeout=600,
        stream_timeout=1800,
        config={},
    )

    payload = model_service._build_router_settings_payload(
        settings, {"general": {}, "context_window": {}}
    )

    assert payload["timeout"] == 600
    assert payload["stream_timeout"] == 1800


def test_stream_timeout_migration_is_additive():
    sql = (
        ROOT / "docker" / "db" / "migrations" / "095_router_stream_timeout.sql"
    ).read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS stream_timeout" in sql
    assert "DROP" not in sql.upper()


def test_cache_probe_reads_nested_cached_tokens():
    usage = {"prompt_tokens_details": {"cached_tokens": 123}}

    assert access_cache_probe._cache_read_tokens(usage) == 123
    assert access_cache_probe._cache_read_tokens({"cache_read_input_tokens": 7}) == 7
    assert access_cache_probe._cache_read_tokens({"prompt_cache_hit_tokens": 9}) == 9


def test_cache_probe_detects_absent_metrics():
    assert access_cache_probe._has_cache_metrics({"prompt_tokens": 10}) is False
    assert access_cache_probe._has_cache_metrics({"cache_creation_input_tokens": 0})


def test_history_probe_anthropic_replays_thinking_and_tool_result():
    payload = {
        "content": [
            {"type": "thinking", "thinking": "x", "signature": "sig"},
            {
                "type": "tool_use",
                "id": "tu1",
                "name": "probe_echo",
                "input": {"text": "ok"},
            },
        ]
    }

    body, has_tool, detail = access_history_probe._anthropic_turn2("m", payload, [])

    assert has_tool is True
    assert "thinking" in detail and "tool_use" in detail
    assert body["messages"][1]["content"][0]["type"] == "thinking"
    tool_result = body["messages"][2]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "tu1"


def test_history_probe_openai_replays_tool_calls():
    payload = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "probe_echo", "arguments": "{}"},
                        }
                    ],
                }
            }
        ]
    }

    body, has_tool, detail = access_history_probe._openai_turn2("m", payload)

    assert has_tool is True
    assert "tool_calls" in detail
    assert body["messages"][2]["role"] == "tool"
    assert body["messages"][2]["tool_call_id"] == "call-1"


@pytest.mark.asyncio
async def test_health_check_maps_litellm_endpoints(monkeypatch):
    model = SimpleNamespace(id=1, model_id="m")
    credential = SimpleNamespace(
        credential_name="cred",
        credential_info={"format": "openai"},
        is_active=True,
    )
    deployment = SimpleNamespace(
        id=10,
        model_id=1,
        litellm_model_id="dep-1",
        credential_id=1,
        credential=credential,
        deploy_name="d",
        is_active=True,
    )

    async def find_by_id(session, model_id):
        return model

    async def find_deployments(session, model_id):
        return [deployment]

    async def check_health(model_name):
        assert model_name == "m"
        return {
            "healthy_endpoints": [{"model_id": "dep-1"}],
            "unhealthy_endpoints": [],
        }

    monkeypatch.setattr(model_service.model_repo, "find_by_id", find_by_id)
    monkeypatch.setattr(
        model_service.model_repo, "find_deployments_by_model", find_deployments
    )
    monkeypatch.setattr(model_service.litellm_client, "check_health", check_health)

    result = await model_service.check_deployments_health(None, 1)

    assert result["groups"] == [{"group_name": "m", "healthy": 1, "unhealthy": 0}]
    item = result["deployments"][0]
    assert item["synced"] is True
    assert item["healthy"] is True
    assert item["credential_name"] == "cred"


@pytest.mark.asyncio
async def test_health_check_marks_unhealthy_and_truncates_error(monkeypatch):
    model = SimpleNamespace(id=1, model_id="m")
    deployment = SimpleNamespace(
        id=11,
        model_id=1,
        litellm_model_id="dep-2",
        credential_id=None,
        credential=None,
        deploy_name="d2",
        is_active=True,
    )

    async def find_by_id(session, model_id):
        return model

    async def find_deployments(session, model_id):
        return [deployment]

    async def check_health(model_name):
        return {
            "healthy_endpoints": [],
            "unhealthy_endpoints": [
                {"model_id": "dep-2", "error": "x" * 900},
            ],
        }

    monkeypatch.setattr(model_service.model_repo, "find_by_id", find_by_id)
    monkeypatch.setattr(
        model_service.model_repo, "find_deployments_by_model", find_deployments
    )
    monkeypatch.setattr(model_service.litellm_client, "check_health", check_health)

    result = await model_service.check_deployments_health(None, 1)

    item = result["deployments"][0]
    assert item["healthy"] is False
    assert len(item["error"]) == 500
