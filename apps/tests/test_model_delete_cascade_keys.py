"""回归：删除模型时须从所有引用该模型的 Key（含场景 Key）移除绑定。

历史缺陷：delete_model 走 remove_public_resource_from_all_keys，该函数只遍历
主 Key（find_all_main_keys），漏掉场景 Key（personal_scene），导致用户场景 Key
的 models JSONB 残留已删模型；同时 model_budgets 也未清理。
"""

from types import SimpleNamespace

import pytest
import sqlalchemy.orm.attributes as sa_attrs

from repositories import ai_key_repo
from services import ai_key_service, litellm_client, model_service


@pytest.mark.asyncio
async def test_remove_model_from_all_keys_cleans_scene_key_and_budgets(monkeypatch):
    sync_calls: list[dict] = []

    main_key = SimpleNamespace(
        id=1,
        litellm_key_id="lit-main",
        models=["gpt-4o", "claude"],
        model_budgets={"gpt-4o": 10.0, "claude": 5.0},
        rate_limit_mode="none",
    )
    # 场景 Key —— 历史缺陷中被漏掉
    scene_key = SimpleNamespace(
        id=2,
        litellm_key_id="lit-scene",
        models=["gpt-4o"],
        model_budgets={"gpt-4o": 3.0},
        rate_limit_mode="none",
    )
    # 未引用该模型的 Key 不应被改动
    untouched_key = SimpleNamespace(
        id=3,
        litellm_key_id="lit-other",
        models=["claude"],
        model_budgets={"claude": 1.0},
        rate_limit_mode="none",
    )

    async def fake_sync(key_arg, **flags):
        sync_calls.append(flags)

    async def fake_find_referencing(session, model_id_str):
        return [main_key, scene_key]

    async def fake_flush():
        pass

    monkeypatch.setattr(ai_key_service, "_sync_key_to_litellm", fake_sync)
    monkeypatch.setattr(
        ai_key_repo, "find_keys_referencing_model", fake_find_referencing
    )
    monkeypatch.setattr(sa_attrs, "flag_modified", lambda *a, **k: None)

    fake_session = SimpleNamespace(flush=fake_flush)

    await model_service._remove_model_from_all_keys(fake_session, "gpt-4o")

    # 主 Key 与场景 Key 都应移除该模型
    assert main_key.models == ["claude"]
    assert scene_key.models == []
    # model_budgets 同步清理
    assert main_key.model_budgets == {"claude": 5.0}
    assert scene_key.model_budgets == {}
    # 两个引用 Key 都触发 LiteLLM 重同步
    assert len(sync_calls) == 2
    assert all(c["models_changed"] is True for c in sync_calls)


@pytest.mark.asyncio
async def test_remove_model_from_all_keys_skips_unreferenced(monkeypatch):
    """find_keys_referencing_model 只返回引用方，未引用的 Key 不进入循环。"""

    async def fake_sync(key_arg, **flags):
        raise AssertionError("未引用模型的 Key 不应触发同步")

    async def fake_find_referencing(session, model_id_str):
        return []

    async def fake_flush():
        pass

    monkeypatch.setattr(ai_key_service, "_sync_key_to_litellm", fake_sync)
    monkeypatch.setattr(
        ai_key_repo, "find_keys_referencing_model", fake_find_referencing
    )
    monkeypatch.setattr(sa_attrs, "flag_modified", lambda *a, **k: None)

    await model_service._remove_model_from_all_keys(
        SimpleNamespace(flush=fake_flush), "gpt-4o"
    )


@pytest.mark.asyncio
async def test_remove_model_sync_failure_does_not_raise(monkeypatch):
    """单个 Key 同步 LiteLLM 失败不应中断其余 Key 清理。"""

    key_a = SimpleNamespace(
        id=1,
        litellm_key_id="lit-a",
        models=["gpt-4o"],
        model_budgets={},
        rate_limit_mode="none",
    )
    key_b = SimpleNamespace(
        id=2,
        litellm_key_id="lit-b",
        models=["gpt-4o"],
        model_budgets={},
        rate_limit_mode="none",
    )

    call_count = {"n": 0}

    async def fake_sync(key_arg, **flags):
        call_count["n"] += 1
        if key_arg.id == 1:
            raise litellm_client.LiteLLMError("boom")

    async def fake_find_referencing(session, model_id_str):
        return [key_a, key_b]

    async def fake_flush():
        pass

    monkeypatch.setattr(ai_key_service, "_sync_key_to_litellm", fake_sync)
    monkeypatch.setattr(
        ai_key_repo, "find_keys_referencing_model", fake_find_referencing
    )
    monkeypatch.setattr(sa_attrs, "flag_modified", lambda *a, **k: None)

    await model_service._remove_model_from_all_keys(
        SimpleNamespace(flush=fake_flush), "gpt-4o"
    )

    # 两个 Key 的本地 JSONB 都已清理，同步失败不阻断
    assert key_a.models == []
    assert key_b.models == []
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_remove_model_from_access_groups_cleans_references(monkeypatch):
    """删除模型时须从引用该模型的访问组 model_ids 移除（历史缺陷：delete_model 不清访问组）。"""
    from repositories import model_repo

    group_a = SimpleNamespace(id=1, group_name="A", model_ids=["gpt-4o", "claude"])
    group_b = SimpleNamespace(id=2, group_name="B", model_ids=["gpt-4o"])
    group_c = SimpleNamespace(id=3, group_name="C", model_ids=["claude"])

    async def fake_find_groups(session, model_id_str):
        return [group_a, group_b]

    async def fake_flush():
        pass

    monkeypatch.setattr(
        model_repo, "find_access_groups_referencing_model", fake_find_groups
    )
    monkeypatch.setattr(sa_attrs, "flag_modified", lambda *a, **k: None)

    await model_service._remove_model_from_access_groups(
        SimpleNamespace(flush=fake_flush), "gpt-4o"
    )

    assert group_a.model_ids == ["claude"]
    assert group_b.model_ids == []
    assert group_c.model_ids == ["claude"]  # 未引用的访问组不动
