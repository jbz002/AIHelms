from types import SimpleNamespace

import pytest

from services.model_service import _build_litellm_params_for_sync


class FakeResult:
    def __init__(self, prefix_info: object) -> None:
        self.prefix_info = prefix_info

    def scalar_one_or_none(self) -> object:
        return self.prefix_info


class FakeSession:
    def __init__(self, provider_type: str, prefix: str, needs_v1: bool) -> None:
        self.provider_type = provider_type
        self.prefix_info = SimpleNamespace(prefix=prefix, needs_v1=needs_v1)

    async def scalar(self, statement: object) -> str:
        return self.provider_type

    async def execute(self, statement: object) -> FakeResult:
        return FakeResult(self.prefix_info)


def build_credential(api_base: str) -> SimpleNamespace:
    return SimpleNamespace(
        provider_id=1,
        credential_name="test-credential",
        credential_values={"api_base": api_base},
        credential_info={"format": "openai"},
    )


@pytest.mark.asyncio
async def test_tencent_chat_uses_native_prefix_and_keeps_v1() -> None:
    result = await _build_litellm_params_for_sync(
        {"model": "hy3"},
        SimpleNamespace(model_id="hy3", category="chat"),
        build_credential("https://tokenhub.tencentmaas.com/v1"),
        FakeSession("tencent", "tencent", False),
    )

    assert result["model"] == "tencent/hy3"
    assert result["api_base"] == "https://tokenhub.tencentmaas.com/v1"


@pytest.mark.asyncio
async def test_xai_chat_uses_native_prefix_and_keeps_v1() -> None:
    result = await _build_litellm_params_for_sync(
        {"model": "grok-4"},
        SimpleNamespace(model_id="grok-4", category="chat"),
        build_credential("https://api.x.ai/v1"),
        FakeSession("xai", "xai", False),
    )

    assert result["model"] == "xai/grok-4"
    assert result["api_base"] == "https://api.x.ai/v1"


@pytest.mark.asyncio
async def test_upstream_vendor_prefixed_model_name_preserved() -> None:
    """上游聚合网关模型全名自带 vendor 前缀：仅外层加 provider 前缀，不剥用户输入。

    2026-09-11 prod 事故：CommandCode 网关要求 model=deepseek/deepseek-v4.1-flash，
    旧逻辑 split("/")[-1] 把 vendor 命名空间剥成裸名，上游 400 not supported。
    """
    result = await _build_litellm_params_for_sync(
        {"model": "deepseek/deepseek-v4.1-flash"},
        SimpleNamespace(model_id="deepseek-v4.1-flash", category="chat"),
        build_credential("https://api.commandcode.ai/provider/v1"),
        FakeSession("other", "openai", False),
    )

    assert result["model"] == "openai/deepseek/deepseek-v4.1-flash"


@pytest.mark.asyncio
async def test_stored_params_with_matching_prefix_rebuild_unchanged() -> None:
    """存量 DB params（剥后重拼过的 openai/xxx）重跑 sync：剥旧前缀重拼，结果不变。"""
    result = await _build_litellm_params_for_sync(
        {"model": "openai/deepseek-v4.1-flash"},
        SimpleNamespace(model_id="deepseek-v4.1-flash", category="chat"),
        build_credential("https://api.commandcode.ai/provider/v1"),
        FakeSession("other", "openai", False),
    )

    assert result["model"] == "openai/deepseek-v4.1-flash"


@pytest.mark.asyncio
async def test_user_written_matching_prefix_stripped_and_rebuilt() -> None:
    """用户手写与解析前缀一致的前缀（openai/gpt-4o）：剥掉重拼，语义不变。"""
    result = await _build_litellm_params_for_sync(
        {"model": "openai/gpt-4o"},
        SimpleNamespace(model_id="gpt-4o", category="chat"),
        build_credential("https://api.commandcode.ai/provider/v1"),
        FakeSession("other", "openai", False),
    )

    assert result["model"] == "openai/gpt-4o"
