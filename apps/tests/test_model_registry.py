"""模型注册表 loader 单测(读 LiteLLM 全量快照,不依赖 DB)。"""

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
