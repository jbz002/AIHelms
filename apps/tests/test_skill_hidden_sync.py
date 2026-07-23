"""回归：治理下架/恢复 set_hidden 必须同步主 Key skills。

历史缺陷：set_hidden 只改 Skill.hidden，未调 remove/sync_public_resource_from_all_keys，
导致下架后主 Key 仍残留 skill id，用户端"我的AI身份"展示成 #id 孤儿。
"""

from types import SimpleNamespace

import pytest

from services import ai_key_service, skill_service


def _skill(**overrides):
    base = dict(
        id=10,
        is_published=True,
        requires_approval=False,
        hidden=False,
        visibility_type="all",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch(monkeypatch, skill):
    calls: dict[str, list] = {"sync": [], "remove": []}

    async def fake_find_by_id(session, skill_id):
        return skill

    async def fake_sync(session, resource_type, resource_id):
        calls["sync"].append((resource_type, resource_id))

    async def fake_remove(session, resource_type, resource_id):
        calls["remove"].append((resource_type, resource_id))

    async def fake_latest(session, skills):
        return {}

    monkeypatch.setattr(skill_service.skill_repo, "find_by_id", fake_find_by_id)
    monkeypatch.setattr(ai_key_service, "sync_public_resource_to_all_keys", fake_sync)
    monkeypatch.setattr(
        ai_key_service, "remove_public_resource_from_all_keys", fake_remove
    )
    monkeypatch.setattr(skill_service, "_latest_audit_map", fake_latest)
    monkeypatch.setattr(skill_service, "_serialize", lambda *a, **k: {})
    return calls


@pytest.mark.asyncio
async def test_set_hidden_true_removes_skill_from_main_keys(monkeypatch):
    skill = _skill(hidden=False)
    calls = _patch(monkeypatch, skill)

    fake_session = SimpleNamespace(
        commit=_async_noop,
        refresh=_async_noop,
    )

    await skill_service.set_hidden(fake_session, skill.id, hidden=True, actor_id=1)

    assert skill.hidden is True
    assert calls["remove"] == [("skills", 10)]
    assert not calls["sync"], "下架不应再广播同步"


@pytest.mark.asyncio
async def test_set_hidden_false_resyncs_when_list_visible(monkeypatch):
    skill = _skill(hidden=True)
    calls = _patch(monkeypatch, skill)

    fake_session = SimpleNamespace(commit=_async_noop, refresh=_async_noop)

    await skill_service.set_hidden(fake_session, skill.id, hidden=False, actor_id=1)

    assert skill.hidden is False
    assert calls["sync"] == [("skills", 10)]
    assert not calls["remove"]


@pytest.mark.asyncio
async def test_set_hidden_true_on_unlisted_skill_still_removes(monkeypatch):
    """未进列表的 skill（unlisted）下架：仍应移除，不广播。"""
    skill = _skill(visibility_type="unlisted")
    calls = _patch(monkeypatch, skill)

    fake_session = SimpleNamespace(commit=_async_noop, refresh=_async_noop)

    await skill_service.set_hidden(fake_session, skill.id, hidden=True, actor_id=1)

    assert calls["remove"] == [("skills", 10)]
    assert not calls["sync"]


def test_is_list_visible_to_public_rules():
    assert skill_service._is_list_visible_to_public(_skill()) is True
    assert skill_service._is_list_visible_to_public(_skill(hidden=True)) is False
    assert skill_service._is_list_visible_to_public(_skill(is_published=False)) is False
    assert (
        skill_service._is_list_visible_to_public(_skill(requires_approval=True))
        is False
    )
    assert (
        skill_service._is_list_visible_to_public(_skill(visibility_type="unlisted"))
        is False
    )
    assert (
        skill_service._is_list_visible_to_public(_skill(visibility_type="private"))
        is False
    )
    assert (
        skill_service._is_list_visible_to_public(_skill(visibility_type="selected"))
        is True
    )


async def _async_noop(*_a, **_k):
    return None
