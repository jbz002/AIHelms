"""回归：is_active=False 的模型不得作为公开资源同步进主 Key。

历史缺陷：_sync_published_model_to_main_keys 只看 is_published + requires_approval，
不检查 is_active；update_model 改 is_active 时也不触发 Key 同步。
结果禁用/删除的模型 id 残留在主 Key 的 models JSONB，前端「可用 AI 资源」计数
比实际可选池多（表现为 6/5，多出来 1 个）。
"""

from types import SimpleNamespace

import pytest

from services import ai_key_service, model_service


@pytest.mark.asyncio
async def test_inactive_model_removed_from_keys(monkeypatch):
    synced: list = []
    removed: list = []

    async def fake_sync(session, rtype, rid):
        synced.append((rtype, rid))
        return 0

    async def fake_remove(session, rtype, rid):
        removed.append((rtype, rid))
        return 0

    monkeypatch.setattr(ai_key_service, "sync_public_resource_to_all_keys", fake_sync)
    monkeypatch.setattr(
        ai_key_service, "remove_public_resource_from_all_keys", fake_remove
    )

    inactive = SimpleNamespace(
        model_id="m1", is_published=True, requires_approval=False, is_active=False
    )
    await model_service._sync_published_model_to_main_keys(None, inactive)

    assert not synced, "inactive 模型不应同步进主 Key"
    assert removed == [("models", "m1")], "inactive 模型应从主 Key 移除"


@pytest.mark.asyncio
async def test_active_published_model_synced_to_keys(monkeypatch):
    synced: list = []
    removed: list = []

    async def fake_sync(session, rtype, rid):
        synced.append((rtype, rid))
        return 1

    async def fake_remove(session, rtype, rid):
        removed.append((rtype, rid))
        return 0

    monkeypatch.setattr(ai_key_service, "sync_public_resource_to_all_keys", fake_sync)
    monkeypatch.setattr(
        ai_key_service, "remove_public_resource_from_all_keys", fake_remove
    )

    active = SimpleNamespace(
        model_id="m2", is_published=True, requires_approval=False, is_active=True
    )
    await model_service._sync_published_model_to_main_keys(None, active)

    assert synced == [("models", "m2")]
    assert not removed
