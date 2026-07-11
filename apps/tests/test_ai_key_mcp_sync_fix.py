"""Phase 0a 回归：移除/同步公开 MCP 资源时须触发 LiteLLM allowed_mcp_servers 重同步。

历史缺陷：sync/remove_public_resource_from_all_keys 仅对 models 触发
_sync_key_to_litellm，对 mcps 只改 JSONB 列不推 LiteLLM，导致已发布 MCP
的弃用/下线与 LiteLLM 不一致。
"""

from types import SimpleNamespace

import pytest
import sqlalchemy.orm.attributes as sa_attrs

from repositories import ai_key_repo
from services import ai_key_service


@pytest.mark.asyncio
async def test_remove_mcp_public_resource_triggers_litellm_sync(monkeypatch):
    sync_calls: list[dict] = []

    key = SimpleNamespace(
        id=1,
        litellm_key_id="lit-1",
        mcps=[42],
        models=[],
        rate_limit_mode="none",
    )

    async def fake_sync(key_arg, **flags):
        sync_calls.append(flags)

    async def fake_find_main(session):
        return [key]

    async def fake_flush():
        pass

    monkeypatch.setattr(ai_key_service, "_sync_key_to_litellm", fake_sync)
    monkeypatch.setattr(ai_key_repo, "find_all_main_keys", fake_find_main)
    monkeypatch.setattr(sa_attrs, "flag_modified", lambda *a, **k: None)

    fake_session = SimpleNamespace(flush=fake_flush)

    updated = await ai_key_service.remove_public_resource_from_all_keys(
        fake_session, "mcps", 42
    )

    assert updated == 1
    assert key.mcps == []  # 资源已从 JSONB 列移除
    assert sync_calls, "mcps 移除应触发 LiteLLM 同步（历史缺陷：曾只对 models 触发）"
    assert sync_calls[0]["mcps_changed"] is True
    assert sync_calls[0]["models_changed"] is False


@pytest.mark.asyncio
async def test_sync_mcp_public_resource_triggers_litellm_sync(monkeypatch):
    sync_calls: list[dict] = []

    key = SimpleNamespace(
        id=2,
        litellm_key_id="lit-2",
        mcps=[],
        models=[7],
        rate_limit_mode="none",
    )

    async def fake_sync(key_arg, **flags):
        sync_calls.append(flags)

    async def fake_find_main(session):
        return [key]

    async def fake_flush():
        pass

    monkeypatch.setattr(ai_key_service, "_sync_key_to_litellm", fake_sync)
    monkeypatch.setattr(ai_key_repo, "find_all_main_keys", fake_find_main)
    monkeypatch.setattr(sa_attrs, "flag_modified", lambda *a, **k: None)

    fake_session = SimpleNamespace(flush=fake_flush)

    await ai_key_service.sync_public_resource_to_all_keys(fake_session, "mcps", 99)

    assert key.mcps == [99]
    assert sync_calls and sync_calls[0]["mcps_changed"] is True
