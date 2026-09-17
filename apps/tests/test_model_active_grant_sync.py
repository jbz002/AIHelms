"""回归：is_active=False 的模型不得作为公开资源同步进主 Key。

历史缺陷：_sync_published_model_to_main_keys 只看 is_published + requires_approval，
不检查 is_active；update_model 改 is_active 时也不触发 Key 同步。
结果禁用/删除的模型 id 残留在主 Key 的 models JSONB，前端「可用 AI 资源」计数
比实际可选池多（表现为 6/5，多出来 1 个）。

合并 upstream e1e5336 后同步改为按用户定向（sync_model_access_to_personal_main_keys），
本回归改为断言目标用户集合口径。
"""

from types import SimpleNamespace

import pytest

from services import ai_key_service, model_service


@pytest.mark.asyncio
async def test_inactive_model_removed_from_keys(monkeypatch):
    calls: list = []

    async def fake_sync(session, model_id, target_user_ids):
        calls.append((model_id, target_user_ids))
        return 0

    monkeypatch.setattr(
        ai_key_service, "sync_model_access_to_personal_main_keys", fake_sync
    )

    inactive = SimpleNamespace(
        model_id="m1", is_published=True, requires_approval=False, is_active=False
    )
    await model_service._sync_published_model_to_main_keys(None, inactive)

    assert calls == [("m1", [])], "inactive 模型应定向清空所有用户授权"


@pytest.mark.asyncio
async def test_active_published_model_synced_to_keys(monkeypatch):
    calls: list = []

    async def fake_sync(session, model_id, target_user_ids):
        calls.append((model_id, target_user_ids))
        return 1

    monkeypatch.setattr(
        ai_key_service, "sync_model_access_to_personal_main_keys", fake_sync
    )

    active = SimpleNamespace(
        model_id="m2",
        is_published=True,
        requires_approval=False,
        is_active=True,
        visibility_type="all",
    )
    await model_service._sync_published_model_to_main_keys(None, active)

    assert calls == [("m2", None)], "公开免审批模型目标为全体合格用户"
