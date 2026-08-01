from types import SimpleNamespace

import pytest

from services import access_test_precheck


class FakeSession:
    pass


async def fake_find_personal_main_active(session, user_id: int):
    return SimpleNamespace(
        id=7,
        is_active=True,
        litellm_key_id="sk-test-key",
        models=["deepseek-chat"],
    )


async def fake_find_deployments_by_model_active(session, model_id: int):
    return [SimpleNamespace(is_active=True, credential=SimpleNamespace(is_active=True))]


# ── 普通用户：个人主 Key 校验 ──


@pytest.mark.asyncio
async def test_access_test_precheck_no_identity_returns_no_identity(
    monkeypatch,
) -> None:
    async def fake_find_personal_main(session, user_id: int):
        return None

    monkeypatch.setattr(
        access_test_precheck.ai_key_repo,
        "find_personal_main",
        fake_find_personal_main,
    )

    api_key, detail = await access_test_precheck.precheck_access_test(
        FakeSession(),
        1,
        SimpleNamespace(id=1, is_active=True, is_published=True),
        "deepseek-chat",
        is_admin=False,
    )

    assert api_key is None
    assert detail is not None
    assert detail["category"] == "no_identity"


@pytest.mark.asyncio
async def test_access_test_precheck_unauthorized_model_returns_permission_help(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        access_test_precheck.ai_key_repo,
        "find_personal_main",
        fake_find_personal_main_active,
    )

    api_key, detail = await access_test_precheck.precheck_access_test(
        FakeSession(),
        1,
        SimpleNamespace(id=1, is_active=True, is_published=True),
        "gpt-4o",
        is_admin=False,
    )

    assert api_key is None
    assert detail is not None
    assert detail["category"] == "model_not_authorized"


@pytest.mark.asyncio
async def test_access_test_precheck_unpublished_model_returns_publish_help(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        access_test_precheck.ai_key_repo,
        "find_personal_main",
        fake_find_personal_main_active,
    )

    api_key, detail = await access_test_precheck.precheck_access_test(
        FakeSession(),
        1,
        SimpleNamespace(id=1, is_active=True, is_published=False),
        "deepseek-chat",
        is_admin=False,
    )

    assert api_key is None
    assert detail is not None
    assert detail["category"] == "model_not_published"


@pytest.mark.asyncio
async def test_access_test_precheck_no_active_deployment_returns_deployment_help(
    monkeypatch,
) -> None:
    async def fake_find_deployments_by_model(session, model_id: int):
        return [SimpleNamespace(is_active=False, credential=None)]

    monkeypatch.setattr(
        access_test_precheck.ai_key_repo,
        "find_personal_main",
        fake_find_personal_main_active,
    )
    monkeypatch.setattr(
        access_test_precheck.model_repo,
        "find_deployments_by_model",
        fake_find_deployments_by_model,
    )

    api_key, detail = await access_test_precheck.precheck_access_test(
        FakeSession(),
        1,
        SimpleNamespace(id=1, is_active=True, is_published=True),
        "deepseek-chat",
        is_admin=False,
    )

    assert api_key is None
    assert detail is not None
    assert detail["category"] == "no_active_deployment"


@pytest.mark.asyncio
async def test_access_test_precheck_ready_returns_key_without_error(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        access_test_precheck.ai_key_repo,
        "find_personal_main",
        fake_find_personal_main_active,
    )
    monkeypatch.setattr(
        access_test_precheck.model_repo,
        "find_deployments_by_model",
        fake_find_deployments_by_model_active,
    )

    api_key, detail = await access_test_precheck.precheck_access_test(
        FakeSession(),
        1,
        SimpleNamespace(id=1, is_active=True, is_published=True),
        "deepseek-chat",
        is_admin=False,
    )

    assert api_key == "sk-test-key"
    assert detail is None


# ── 管理员：优先个人主 Key，回退 master key（统一归因）──


async def _fake_resolve_with_key(session, user, model_name):
    return ("sk-resolved", "aihelms_user_1")


async def _fake_resolve_empty(session, user, model_name):
    return ("", "")


@pytest.mark.asyncio
async def test_access_test_precheck_admin_ready_returns_resolved_key(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        access_test_precheck.platform_llm,
        "resolve_call_identity",
        _fake_resolve_with_key,
    )
    monkeypatch.setattr(
        access_test_precheck.model_repo,
        "find_deployments_by_model",
        fake_find_deployments_by_model_active,
    )

    api_key, detail = await access_test_precheck.precheck_access_test(
        FakeSession(),
        1,
        SimpleNamespace(
            id=1,
            model_id="draft-model",
            is_active=True,
            is_published=False,
        ),
        "draft-model",
        is_admin=True,
    )

    assert api_key == "sk-resolved"
    assert detail is None


@pytest.mark.asyncio
async def test_access_test_precheck_admin_model_none_returns_resolved_key(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        access_test_precheck.platform_llm,
        "resolve_call_identity",
        _fake_resolve_with_key,
    )

    api_key, detail = await access_test_precheck.precheck_access_test(
        FakeSession(),
        1,
        None,
        "draft-model",
        is_admin=True,
    )

    assert api_key == "sk-resolved"
    assert detail is None


@pytest.mark.asyncio
async def test_access_test_precheck_admin_no_platform_key_returns_platform_help(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        access_test_precheck.platform_llm,
        "resolve_call_identity",
        _fake_resolve_empty,
    )

    api_key, detail = await access_test_precheck.precheck_access_test(
        FakeSession(),
        1,
        SimpleNamespace(
            id=1,
            model_id="draft-model",
            is_active=True,
            is_published=True,
        ),
        "draft-model",
        is_admin=True,
    )

    assert api_key is None
    assert detail is not None
    assert detail["category"] == "no_platform_key"


@pytest.mark.asyncio
async def test_access_test_precheck_admin_inactive_model_returns_deployment_help(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        access_test_precheck.platform_llm,
        "resolve_call_identity",
        _fake_resolve_with_key,
    )

    api_key, detail = await access_test_precheck.precheck_access_test(
        FakeSession(),
        1,
        SimpleNamespace(
            id=1,
            model_id="draft-model",
            is_active=False,
            is_published=False,
        ),
        "draft-model",
        is_admin=True,
    )

    assert api_key is None
    assert detail is not None
    assert detail["category"] == "no_active_deployment"


@pytest.mark.asyncio
async def test_access_test_precheck_admin_no_deployment_returns_deployment_help(
    monkeypatch,
) -> None:
    async def fake_find_deployments_by_model(session, model_id: int):
        return [SimpleNamespace(is_active=False, credential=None)]

    monkeypatch.setattr(
        access_test_precheck.platform_llm,
        "resolve_call_identity",
        _fake_resolve_with_key,
    )
    monkeypatch.setattr(
        access_test_precheck.model_repo,
        "find_deployments_by_model",
        fake_find_deployments_by_model,
    )

    api_key, detail = await access_test_precheck.precheck_access_test(
        FakeSession(),
        1,
        SimpleNamespace(
            id=1,
            model_id="draft-model",
            is_active=True,
            is_published=False,
        ),
        "draft-model",
        is_admin=True,
    )

    assert api_key is None
    assert detail is not None
    assert detail["category"] == "no_active_deployment"
