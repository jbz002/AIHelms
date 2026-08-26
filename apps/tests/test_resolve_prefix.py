"""_resolve_prefix 三层兜底单测：覆盖表 → registry 派生 → None。

复用 test_provider_prefix_routing.py 的 FakeSession 模式，不依赖真实 DB。
"""

from types import SimpleNamespace

import pytest

from services.model_service import _resolve_prefix, resolve_prefix_for_preview


class FakeResult:
    def __init__(self, row: object) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class FakeSession:
    """scalar 返回 provider_type；execute 返回 override 行（None 表示覆盖表未命中）。"""

    def __init__(self, provider_type: str, override: object = None) -> None:
        self.provider_type = provider_type
        self.override = override

    async def scalar(self, statement: object) -> str:
        return self.provider_type

    async def execute(self, statement: object) -> FakeResult:
        return FakeResult(self.override)


def credential() -> SimpleNamespace:
    return SimpleNamespace(provider_id=1, credential_info={"format": "openai"})


@pytest.mark.asyncio
async def test_override_hit_returns_table_row() -> None:
    """覆盖表命中：legacy google→gemini 不变（向后兼容）。"""
    override = SimpleNamespace(prefix="gemini", needs_v1=False)
    result = await _resolve_prefix(
        FakeSession("google", override), credential(), "chat"
    )
    assert result is override


@pytest.mark.asyncio
async def test_normalize_fallback_for_registry_native() -> None:
    """覆盖表未命中 + registry 原生 provider：派生前缀。"""
    result = await _resolve_prefix(
        FakeSession("fireworks_ai", None), credential(), "chat"
    )
    assert result is not None
    assert result.prefix == "fireworks_ai"
    assert result.needs_v1 is False


@pytest.mark.asyncio
async def test_normalize_folds_vertex_subclass() -> None:
    result = await _resolve_prefix(
        FakeSession("vertex_ai-anthropic_models", None), credential(), "chat"
    )
    assert result is not None
    assert result.prefix == "vertex_ai"


@pytest.mark.asyncio
async def test_unknown_returns_none() -> None:
    """非 registry 原生 + 无覆盖：返回 None（不误派生，交给 anthropic 兜底或裸 model）。"""
    assert (
        await _resolve_prefix(
            FakeSession("totally_new_vendor", None), credential(), "chat"
        )
        is None
    )


@pytest.mark.asyncio
async def test_legacy_google_unaffected_without_override() -> None:
    """legacy google 无覆盖行时返回 None（保持现状，不会被误派生成 'google' 前缀）。"""
    assert (
        await _resolve_prefix(FakeSession("google", None), credential(), "chat") is None
    )


@pytest.mark.asyncio
async def test_no_credential_returns_none() -> None:
    assert await _resolve_prefix(FakeSession("openai"), None, "chat") is None


@pytest.mark.asyncio
async def test_registry_native_anthropic_credential_redirected_to_fallback() -> None:
    """registry 原生 provider + anthropic 方言 chat 凭证 + 覆盖表无行：必须返 None
    交还 anthropic 硬编码兜底，不得派生供应商前缀（2026-08-26 ollama 事故回归）。

    派生 'ollama/' 会让 litellm 用 openai 方言 handler 调 anthropic 端点，
    翻译路径丢 tool_use，Claude Code 调工具卡死。
    """
    anthropic_credential = SimpleNamespace(
        provider_id=1, credential_info={"format": "anthropic"}
    )
    assert (
        await _resolve_prefix(FakeSession("ollama", None), anthropic_credential, "chat")
        is None
    )


@pytest.mark.asyncio
async def test_registry_native_openai_credential_keeps_derived_prefix() -> None:
    """openai 方言凭证不受加固影响：ollama 照常派生 'ollama' 前缀。"""
    result = await _resolve_prefix(FakeSession("ollama", None), credential(), "chat")
    assert result is not None
    assert result.prefix == "ollama"


@pytest.mark.asyncio
async def test_anthropic_provider_native_derive_unchanged() -> None:
    """provider=anthropic 自身派生即 'anthropic'，加固不拦截。"""
    anthropic_credential = SimpleNamespace(
        provider_id=1, credential_info={"format": "anthropic"}
    )
    result = await _resolve_prefix(
        FakeSession("anthropic", None), anthropic_credential, "chat"
    )
    assert result is not None
    assert result.prefix == "anthropic"


def test_apply_credential_passthrough_extra_headers() -> None:
    """凭证级 extra_headers 透传进 litellm_params（Bearer 认证风格差异的通用通道）。"""
    from services.model_service import _apply_credential_to_litellm_params

    cred = SimpleNamespace(
        credential_name="ollama-anthropic",
        credential_values={
            "api_base": "https://ollama.com",
            "extra_headers": {"Authorization": "Bearer sk-test"},
        },
        credential_info={"format": "anthropic"},
    )
    params = _apply_credential_to_litellm_params({"model": "x"}, cred)
    assert params["extra_headers"] == {"Authorization": "Bearer sk-test"}

    # 凭证未配置 extra_headers 时，部署行已有的副本必须保留（防 UI 覆写丢认证头）
    cred_without = SimpleNamespace(
        credential_name="ollama-anthropic",
        credential_values={"api_base": "https://ollama.com"},
        credential_info={"format": "anthropic"},
    )
    params_kept = _apply_credential_to_litellm_params(
        {"model": "x", "extra_headers": {"Authorization": "Bearer old"}}, cred_without
    )
    assert params_kept["extra_headers"] == {"Authorization": "Bearer old"}


@pytest.mark.asyncio
async def test_resolve_prefix_for_preview_sources() -> None:
    assert (
        await resolve_prefix_for_preview(
            FakeSession("google", SimpleNamespace(prefix="gemini", needs_v1=False)),
            1,
            "openai",
            "chat",
        )
    )["source"] == "override"
    assert (
        await resolve_prefix_for_preview(
            FakeSession("fireworks_ai", None), 1, "openai", "chat"
        )
    )["source"] == "derived"
    assert (
        await resolve_prefix_for_preview(
            FakeSession("totally_new", None), 1, "openai", "chat"
        )
    )["source"] == "none"
