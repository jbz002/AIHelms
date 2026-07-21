"""策略预设 resolve_policy 单元测试（S2）。纯函数，不依赖 DB。"""

from types import SimpleNamespace

from services.ai_policies_policies import POLICIES, list_presets, resolve_policy


def _settings(**kw):
    base = {
        "default_policy": "balanced",
        "policy_overrides": {},
        "llm_consensus_runs": 0,
        "regex_enabled": True,
        "llm_review_enabled": False,
        "llm_review_model_id": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _audit(policy: str = ""):
    return SimpleNamespace(policy=policy)


def test_audit_policy_freezes_overrides_everything():
    spec = resolve_policy(
        _settings(default_policy="permissive"), _audit(policy="strict")
    )
    assert spec.name == "strict"
    assert spec.fail_on_severity == "medium"


def test_category_override_beats_db_default():
    settings = _settings(
        default_policy="balanced", policy_overrides={"coding": "strict"}
    )
    assert resolve_policy(settings, _audit(), "coding").name == "strict"


def test_db_default_when_no_audit_no_override():
    assert (
        resolve_policy(_settings(default_policy="permissive"), _audit()).name
        == "permissive"
    )


def test_llm_disabled_removes_consensus_analyzer():
    spec = resolve_policy(_settings(llm_review_enabled=False), _audit())
    assert "llm_consensus" not in spec.analyzers


def test_llm_enabled_keeps_consensus_analyzer():
    spec = resolve_policy(_settings(llm_review_enabled=True), _audit())
    assert "llm_consensus" in spec.analyzers


def test_regex_disabled_removes_regex_analyzer():
    spec = resolve_policy(_settings(regex_enabled=False), _audit())
    assert "regex" not in spec.analyzers


def test_consensus_runs_setting_overrides_preset():
    spec = resolve_policy(
        _settings(llm_consensus_runs=5, llm_review_enabled=True), _audit()
    )
    assert spec.llm_consensus_runs == 5


def test_list_presets_returns_three_presets():
    presets = list_presets()
    assert {p["name"] for p in presets} == {"strict", "balanced", "permissive"}


def test_policies_table_keys_match_names():
    assert set(POLICIES) == {"strict", "balanced", "permissive"}
