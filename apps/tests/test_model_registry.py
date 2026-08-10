"""模型注册表 loader 单测(读 LiteLLM 全量快照,不依赖 DB)。"""

import pathlib
from types import SimpleNamespace

import httpx
import pytest

from services import model_registry


def test_lookup_exact_openai() -> None:
    entry = model_registry.lookup("gpt-4o")
    assert entry is not None
    assert entry["model_name"] == "gpt-4o"
    assert entry["litellm_provider"] == "openai"


def test_lookup_exact_with_prefix() -> None:
    entry = model_registry.lookup("zai/glm-4.7")
    assert entry is not None
    assert entry["litellm_provider"] == "zai"


def test_lookup_case_insensitive() -> None:
    entry = model_registry.lookup("GPT-4O")
    assert entry is not None
    assert entry["model_name"] == "gpt-4o"


def test_lookup_glm5_exists() -> None:
    entry = model_registry.lookup("zai/glm-5")
    assert entry is not None
    assert entry["litellm_provider"] == "zai"


def test_lookup_not_found() -> None:
    assert model_registry.lookup("nonexistent-xyz-12345") is None
    assert model_registry.lookup("") is None
    assert model_registry.lookup("   ") is None


def test_search() -> None:
    results = model_registry.search("gpt-4o", limit=5000)
    assert len(results) > 0
    assert all("gpt-4o" in k.lower() for k in results)


def test_search_empty_returns_many() -> None:
    results = model_registry.search("", limit=5000)
    assert len(results) > 2000


def test_total_models_covered() -> None:
    """全量快照应覆盖 2000+ 模型,确保非手抄小集。"""
    all_keys = model_registry.search("", limit=5000)
    assert len(all_keys) > 2000


async def test_refresh_disabled_by_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto_update=False 时不联网。"""
    monkeypatch.setattr(model_registry.settings, "model_registry_auto_update", False)
    assert await model_registry.refresh_from_remote() is False


async def test_refresh_skipped_when_local_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本地快照足够新时跳过拉取（不触网）。"""
    monkeypatch.setattr(model_registry.settings, "model_registry_auto_update", True)
    monkeypatch.setattr(
        model_registry.settings, "model_registry_refresh_min_age_hours", 999_999
    )
    assert await model_registry.refresh_from_remote() is False


async def test_refresh_degrades_on_fetch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """拉取失败时静默降级，返回 False，不抛、不动本地文件。"""
    monkeypatch.setattr(model_registry.settings, "model_registry_auto_update", True)
    monkeypatch.setattr(
        model_registry.settings, "model_registry_refresh_min_age_hours", 0
    )

    class _BoomClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_BoomClient":
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def get(self, url: str) -> None:
            raise httpx.TimeoutException("simulated timeout")

    monkeypatch.setattr(model_registry.httpx, "AsyncClient", _BoomClient)
    assert await model_registry.refresh_from_remote() is False


async def test_refresh_falls_back_to_mirror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """主源失败时自动切镜像源。"""
    monkeypatch.setattr(model_registry.settings, "model_registry_auto_update", True)
    monkeypatch.setattr(
        model_registry.settings, "model_registry_refresh_min_age_hours", 0
    )
    monkeypatch.setattr(
        model_registry.settings,
        "model_registry_url",
        "https://primary.invalid/a.json,https://mirror.invalid/b.json",
    )
    monkeypatch.setattr(model_registry, "_REGISTRY_PATH", tmp_path / "registry.json")

    valid = {f"model-{i}": {"litellm_provider": "x"} for i in range(1005)}

    class _FallbackClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_FallbackClient":
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def get(self, url: str) -> SimpleNamespace:
            if "primary" in url:
                raise httpx.TimeoutException("primary timeout")
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: valid)

    monkeypatch.setattr(model_registry.httpx, "AsyncClient", _FallbackClient)
    assert await model_registry.refresh_from_remote() is True
    assert (tmp_path / "registry.json").exists()
