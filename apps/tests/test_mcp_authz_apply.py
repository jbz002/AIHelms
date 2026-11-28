"""apply_compiled 的幂等：内容与上次下发一致时不重复推网关。"""

from types import SimpleNamespace

import pytest

from services import mcp_authz_service


class _Session:
    def __init__(self):
        self.flushes = 0

    async def flush(self):
        self.flushes += 1


@pytest.mark.asyncio
async def test_skip_push_when_hash_matches(monkeypatch):
    calls = []

    async def fake_update_key(**kw):
        calls.append(kw)

    async def fake_build(session, ids, tools=None):
        return {"mcp_servers": ["docs"]}

    async def fake_state(session, key_id):
        return SimpleNamespace(status="synced", applied_hash="h1")

    async def fake_upsert(*a, **kw):
        return SimpleNamespace()

    from services import ai_key_service

    monkeypatch.setattr(mcp_authz_service.litellm_client, "update_key", fake_update_key)
    monkeypatch.setattr(ai_key_service, "build_object_permission", fake_build)
    monkeypatch.setattr(mcp_authz_service.mcp_authz_repo, "get_sync_state", fake_state)
    monkeypatch.setattr(
        mcp_authz_service.mcp_authz_repo, "upsert_sync_state", fake_upsert
    )

    key = SimpleNamespace(
        id=1,
        litellm_key_id="sk-x",
        mcps=[1],
        mcp_tools={},
        mcp_toolsets=[],
        mcp_policy_hash="h1",
    )
    compiled = mcp_authz_service.CompiledGrants(
        server_ids=[1], servers=["docs"], tool_permissions={}, policy_hash="h1"
    )
    result = await mcp_authz_service.apply_compiled(_Session(), key, compiled)
    assert result["skipped"] is True
    assert calls == []


@pytest.mark.asyncio
async def test_push_when_state_missing(monkeypatch):
    calls = []

    async def fake_update_key(**kw):
        calls.append(kw)

    async def fake_build(session, ids, tools=None):
        return {"mcp_servers": ["docs"]}

    async def fake_state(session, key_id):
        return None

    async def fake_upsert(*a, **kw):
        return SimpleNamespace()

    from services import ai_key_service

    monkeypatch.setattr(mcp_authz_service.litellm_client, "update_key", fake_update_key)
    monkeypatch.setattr(ai_key_service, "build_object_permission", fake_build)
    monkeypatch.setattr(mcp_authz_service.mcp_authz_repo, "get_sync_state", fake_state)
    monkeypatch.setattr(
        mcp_authz_service.mcp_authz_repo, "upsert_sync_state", fake_upsert
    )

    key = SimpleNamespace(
        id=1,
        litellm_key_id="sk-x",
        mcps=[1],
        mcp_tools={},
        mcp_toolsets=[],
        mcp_policy_hash="h1",
    )
    compiled = mcp_authz_service.CompiledGrants(
        server_ids=[1], servers=["docs"], tool_permissions={}, policy_hash="h1"
    )
    result = await mcp_authz_service.apply_compiled(_Session(), key, compiled)
    assert result["pushed"] is True
    assert len(calls) == 1
