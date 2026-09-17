"""新用户默认 Key 预算/限流配置测试：resolve 解析 + 请求校验 + 主 Key 创建套用。"""

from decimal import Decimal
from types import SimpleNamespace

import pydantic
import pytest

from repositories import platform_settings_repo
from services import ai_key_service, platform_settings_service
from services.platform_settings_service import DefaultKeyConfig


def _settings_row(
    *,
    budget_limit=None,
    budget_hard_limit=False,
    budget_duration=None,
    rate_limit_mode="none",
    tpm_limit=None,
    rpm_limit=None,
    max_parallel_requests=None,
):
    return SimpleNamespace(
        default_model_id=None,
        default_key_budget_limit=budget_limit,
        default_key_budget_hard_limit=budget_hard_limit,
        default_key_budget_duration=budget_duration,
        default_key_rate_limit_mode=rate_limit_mode,
        default_key_tpm_limit=tpm_limit,
        default_key_rpm_limit=rpm_limit,
        default_key_max_parallel_requests=max_parallel_requests,
        updated_by=None,
        updated_at=None,
    )


# --- resolve_default_key_config ---


@pytest.mark.asyncio
async def test_resolve_default_key_config_unconfigured_returns_none(
    monkeypatch,
) -> None:
    async def fake_get(session):
        return _settings_row()

    monkeypatch.setattr(platform_settings_repo, "get_settings", fake_get)
    assert await platform_settings_service.resolve_default_key_config(None) is None


@pytest.mark.asyncio
async def test_resolve_default_key_config_budget_active(monkeypatch) -> None:
    async def fake_get(session):
        return _settings_row(
            budget_limit=Decimal("38.5"),
            budget_hard_limit=True,
            budget_duration="7d",
            tpm_limit=999,
        )

    monkeypatch.setattr(platform_settings_repo, "get_settings", fake_get)
    cfg = await platform_settings_service.resolve_default_key_config(None)
    assert cfg is not None
    assert cfg.budget_limit == Decimal("38.5")
    assert cfg.budget_hard_limit is True
    assert cfg.budget_duration == "7d"
    assert cfg.rate_limit_mode == "none"
    assert cfg.tpm_limit is None


@pytest.mark.asyncio
async def test_resolve_default_key_config_duration_fallback(monkeypatch) -> None:
    async def fake_get(session):
        return _settings_row(budget_limit=Decimal("1"), budget_duration=None)

    monkeypatch.setattr(platform_settings_repo, "get_settings", fake_get)
    cfg = await platform_settings_service.resolve_default_key_config(None)
    assert cfg is not None
    assert cfg.budget_duration == "30d"


@pytest.mark.asyncio
async def test_resolve_default_key_config_rate_active(monkeypatch) -> None:
    async def fake_get(session):
        return _settings_row(
            rate_limit_mode="total",
            tpm_limit=1000,
            rpm_limit=60,
            max_parallel_requests=5,
        )

    monkeypatch.setattr(platform_settings_repo, "get_settings", fake_get)
    cfg = await platform_settings_service.resolve_default_key_config(None)
    assert cfg is not None
    assert cfg.rate_limit_mode == "total"
    assert cfg.tpm_limit == 1000
    assert cfg.rpm_limit == 60
    assert cfg.max_parallel_requests == 5
    assert cfg.budget_limit is None


# --- UpdatePlatformSettingsRequest 校验 ---


def _make_request(**overrides):
    from api.v1.platform_settings import UpdatePlatformSettingsRequest

    return UpdatePlatformSettingsRequest(**overrides)


def test_update_request_invalid_duration_rejected() -> None:
    with pytest.raises(pydantic.ValidationError):
        _make_request(
            default_key_budget_limit=Decimal("1"), default_key_budget_duration="15d"
        )


def test_update_request_mode_total_requires_value() -> None:
    with pytest.raises(pydantic.ValidationError):
        _make_request(default_key_rate_limit_mode="total")


def test_update_request_mode_none_with_values_rejected() -> None:
    with pytest.raises(pydantic.ValidationError):
        _make_request(default_key_rate_limit_mode="none", default_key_tpm_limit=100)


def test_update_request_negative_budget_rejected() -> None:
    with pytest.raises(pydantic.ValidationError):
        _make_request(default_key_budget_limit=Decimal("-1"))


def test_update_request_rate_limit_below_one_rejected() -> None:
    with pytest.raises(pydantic.ValidationError):
        _make_request(default_key_rate_limit_mode="total", default_key_rpm_limit=0)


# --- create_personal_main_key 套用默认值 ---


def _active_config() -> DefaultKeyConfig:
    return DefaultKeyConfig(
        budget_limit=Decimal("10"),
        budget_hard_limit=True,
        budget_duration="7d",
        rate_limit_mode="total",
        tpm_limit=2000,
        rpm_limit=30,
        max_parallel_requests=3,
    )


def _patch_key_env(
    monkeypatch, *, existing=None, defaults=..., resolve_calls=None, patch_loader=True
):
    async def fake_find_main(session, user_id):
        return existing

    async def fake_create(session, key):
        key.id = 123
        return key

    async def fake_public_resources(session, user_id):
        return {"models": ["m1"], "skills": [], "mcps": [], "agents": []}

    async def fake_find_user(session, user_id):
        return SimpleNamespace(litellm_user_id="aihelms_user_1", is_active=True)

    async def fake_expand(session, models, arg):
        return list(models), []

    async def fake_resolve(session):
        if resolve_calls is not None:
            resolve_calls.append(1)
        if defaults is ...:
            raise RuntimeError("resolve should not be called")
        return defaults

    created = {}

    async def fake_litellm_create_key(**kwargs):
        created.update(kwargs)
        return {"key": "sk-new"}

    monkeypatch.setattr(
        ai_key_service.ai_key_repo, "find_personal_main", fake_find_main
    )
    monkeypatch.setattr(ai_key_service.ai_key_repo, "create", fake_create)
    monkeypatch.setattr(ai_key_service, "get_public_resources", fake_public_resources)
    monkeypatch.setattr(ai_key_service.user_repo, "find_user_by_id", fake_find_user)
    monkeypatch.setattr(ai_key_service, "_expand_models_with_anthropic", fake_expand)
    if patch_loader:
        monkeypatch.setattr(ai_key_service, "_load_default_key_config", fake_resolve)
    monkeypatch.setattr(
        ai_key_service.litellm_client, "create_key", fake_litellm_create_key
    )
    return created


@pytest.mark.asyncio
async def test_create_personal_main_key_applies_defaults(monkeypatch) -> None:
    created = _patch_key_env(monkeypatch, defaults=_active_config())
    key = await ai_key_service.create_personal_main_key(None, 1, "alice")
    assert key.budget_limit == Decimal("10")
    assert key.budget_hard_limit is True
    assert key.budget_duration == "7d"
    assert key.rate_limit_mode == "total"
    assert key.tpm_limit == 2000
    assert key.rpm_limit == 30
    assert key.max_parallel_requests == 3
    assert created["tpm_limit"] == 2000
    assert created["rpm_limit"] == 30
    assert created["max_parallel_requests"] == 3
    assert "max_budget" not in created
    assert "duration" not in created


@pytest.mark.asyncio
async def test_create_personal_main_key_unconfigured_keeps_plain(monkeypatch) -> None:
    created = _patch_key_env(monkeypatch, defaults=None)
    key = await ai_key_service.create_personal_main_key(None, 1, "bob")
    assert key.budget_limit is None
    assert key.budget_hard_limit is False
    assert key.budget_duration == "30d"
    assert key.rate_limit_mode == "none"
    assert key.tpm_limit is None
    # litellm_client.create_key 对 None 限流值不发（client 内部过滤），这里只断言传值为空
    assert created.get("tpm_limit") is None
    assert "max_budget" not in created
    assert "duration" not in created


@pytest.mark.asyncio
async def test_create_personal_main_key_idempotent_skips_resolve(monkeypatch) -> None:
    existing = SimpleNamespace(id=9)
    calls = []
    _patch_key_env(monkeypatch, existing=existing, defaults=..., resolve_calls=calls)
    key = await ai_key_service.create_personal_main_key(None, 1, "carol")
    assert key is existing
    assert calls == []


@pytest.mark.asyncio
async def test_create_personal_main_key_settings_failure_degrades(monkeypatch) -> None:
    _patch_key_env(monkeypatch, patch_loader=False)

    async def failing_resolve(session):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        ai_key_service.platform_settings_service,
        "resolve_default_key_config",
        failing_resolve,
    )
    key = await ai_key_service.create_personal_main_key(None, 1, "dave")
    assert key.budget_limit is None
    assert key.rate_limit_mode == "none"
