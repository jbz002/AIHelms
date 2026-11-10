"""P0 路由稳定性回归：fallback 下发、跨方言自动兜底、方言映射计入凭证启停。"""

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from repositories import model_repo
from services import model_service


def _settings(**overrides):
    values = {
        "id": 1,
        "routing_strategy": "simple-shuffle",
        "fallbacks": [],
        "allowed_fails": 3,
        "cooldown_time": 60,
        "num_retries": 2,
        "timeout": 600,
        "stream_timeout": 1800,
        "config": {},
        "updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _model(model_id: str):
    return SimpleNamespace(model_id=model_id)


@pytest.mark.asyncio
async def test_auto_dialect_fallback_generates_bidirectional_entries(monkeypatch):
    async def find_all_active(session):
        return [_model("m-both"), _model("m-openai-only")]

    async def anthropic_ids(session, ids):
        return {"m-both"}

    async def openai_ids(session, ids):
        return {"m-both", "m-openai-only"}

    monkeypatch.setattr(model_service.model_repo, "find_all_active", find_all_active)
    monkeypatch.setattr(
        model_service.model_repo,
        "find_model_ids_with_anthropic_deployments",
        anthropic_ids,
    )
    monkeypatch.setattr(
        model_service.model_repo,
        "find_model_ids_with_openai_deployments",
        openai_ids,
    )

    desired = await model_service._compute_desired_fallbacks(None, _settings())

    assert desired["general"] == {
        "m-both": ["m-both(Anthropic)"],
        "m-both(Anthropic)": ["m-both"],
    }
    assert desired["context_window"] == desired["general"]
    assert "m-openai-only" not in desired["general"]


@pytest.mark.asyncio
async def test_auto_dialect_fallback_can_be_disabled(monkeypatch):
    async def fail(session):
        raise AssertionError("auto fallback disabled must not query models")

    monkeypatch.setattr(model_service.model_repo, "find_all_active", fail)

    settings = _settings(
        fallbacks=[{"a": ["b"]}], config={"auto_dialect_fallback": False}
    )
    desired = await model_service._compute_desired_fallbacks(None, settings)

    assert desired == {"general": {"a": ["b"]}, "context_window": {}}


@pytest.mark.asyncio
async def test_update_router_settings_pushes_global_config_and_fallbacks(monkeypatch):
    stored = _settings(
        fallbacks=[{"a": ["b"]}], config={"auto_dialect_fallback": False}
    )

    async def get_router_settings(session):
        return stored

    async def upsert_router_settings(session, settings):
        return settings

    calls: dict[str, object] = {}

    async def update_router_config(payload):
        calls["config"] = payload
        return {}

    async def get_fallbacks(fallback_type):
        return {}

    async def create_fallback(model, targets, fallback_type="general"):
        calls.setdefault("fallbacks", []).append((model, targets, fallback_type))
        return {}

    async def delete_fallback(model, fallback_type="general"):
        raise AssertionError("no stale fallback expected")

    monkeypatch.setattr(
        model_service.model_repo, "get_router_settings", get_router_settings
    )
    monkeypatch.setattr(
        model_service.model_repo, "upsert_router_settings", upsert_router_settings
    )
    monkeypatch.setattr(
        model_service.litellm_client, "update_router_config", update_router_config
    )
    monkeypatch.setattr(model_service.litellm_client, "get_fallbacks", get_fallbacks)
    monkeypatch.setattr(
        model_service.litellm_client, "create_fallback", create_fallback
    )
    monkeypatch.setattr(
        model_service.litellm_client, "delete_fallback", delete_fallback
    )

    class _Session:
        async def commit(self):
            calls["committed"] = True

        async def refresh(self, _obj):
            return None

    await model_service.update_router_settings(_Session(), num_retries=4, timeout=600)

    assert calls["config"]["num_retries"] == 4
    assert calls["config"]["timeout"] == 600
    assert calls["config"]["fallbacks"] == [{"a": ["b"]}]
    assert calls["config"]["context_window_fallbacks"] == []
    assert calls["fallbacks"] == [("a", ["b"], "general")]
    assert calls["committed"] is True


@pytest.mark.asyncio
async def test_stale_fallbacks_are_deleted(monkeypatch):
    stored = _settings(config={"auto_dialect_fallback": False})

    async def get_router_settings(session):
        return stored

    async def upsert_router_settings(session, settings):
        return settings

    async def update_router_config(payload):
        return {}

    async def get_fallbacks(fallback_type):
        return {"old": ["x"]} if fallback_type == "general" else {}

    deleted: list[tuple[str, str]] = []

    async def create_fallback(model, targets, fallback_type="general"):
        raise AssertionError("no desired fallback expected")

    async def delete_fallback(model, fallback_type="general"):
        deleted.append((model, fallback_type))
        return {}

    monkeypatch.setattr(
        model_service.model_repo, "get_router_settings", get_router_settings
    )
    monkeypatch.setattr(
        model_service.model_repo, "upsert_router_settings", upsert_router_settings
    )
    monkeypatch.setattr(
        model_service.litellm_client, "update_router_config", update_router_config
    )
    monkeypatch.setattr(model_service.litellm_client, "get_fallbacks", get_fallbacks)
    monkeypatch.setattr(
        model_service.litellm_client, "create_fallback", create_fallback
    )
    monkeypatch.setattr(
        model_service.litellm_client, "delete_fallback", delete_fallback
    )

    class _Session:
        async def commit(self):
            return None

        async def refresh(self, _obj):
            return None

    await model_service.update_router_settings(_Session())

    assert deleted == [("old", "general")]


def test_dialect_queries_filter_inactive_credentials():
    class _Result:
        def all(self):
            return []

    class _Session:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            return _Result()

    import asyncio

    session = _Session()
    asyncio.run(model_repo.find_model_ids_with_anthropic_deployments(session, ["m"]))
    asyncio.run(model_repo.find_model_ids_with_openai_deployments(session, ["m"]))

    anthropic_sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    openai_sql = str(session.statements[1].compile(dialect=postgresql.dialect()))

    assert "credentials.is_active" in anthropic_sql
    assert "credentials.is_active" in openai_sql
