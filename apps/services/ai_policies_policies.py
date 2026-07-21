"""安全扫描策略预设（S2）。

预设本体放代码：可测、git 版本化、避免运维误配导致安全降级。
仅「当前默认 preset 名」+「按 Skill 类别覆盖」放 AiPoliciesSettings 表。
"""

from dataclasses import dataclass

from core.config import settings


@dataclass(frozen=True)
class PolicySpec:
    name: str
    analyzers: tuple[str, ...]
    fail_on_severity: str  # medium | high | critical：max_severity >= 该级 → BLOCKED
    llm_consensus_runs: int


POLICIES: dict[str, PolicySpec] = {
    "strict": PolicySpec(
        name="strict",
        analyzers=("regex", "llm_consensus"),
        fail_on_severity="medium",
        llm_consensus_runs=3,
    ),
    "balanced": PolicySpec(
        name="balanced",
        analyzers=("regex", "llm_consensus"),
        fail_on_severity="high",
        llm_consensus_runs=2,
    ),
    "permissive": PolicySpec(
        name="permissive",
        analyzers=("regex",),
        fail_on_severity="critical",
        llm_consensus_runs=1,
    ),
}


def list_presets() -> list[dict]:
    return [
        {
            "name": spec.name,
            "analyzers": list(spec.analyzers),
            "fail_on_severity": spec.fail_on_severity,
            "llm_consensus_runs": spec.llm_consensus_runs,
        }
        for spec in POLICIES.values()
    ]


def _policy_name(settings_row, audit, skill_category: str | None) -> str:
    audit_policy = getattr(audit, "policy", "") or ""
    if audit_policy and audit_policy in POLICIES:
        return audit_policy
    overrides = getattr(settings_row, "policy_overrides", {}) or {}
    if skill_category and overrides.get(skill_category) in POLICIES:
        return overrides[skill_category]
    db_default = getattr(settings_row, "default_policy", "") or ""
    if db_default in POLICIES:
        return db_default
    return (
        settings.ai_policies_default_policy
        if settings.ai_policies_default_policy in POLICIES
        else "balanced"
    )


def resolve_policy(
    settings_row, audit, skill_category: str | None = None
) -> PolicySpec:
    """优先级：audit.policy（创建时冻结）> 按类别覆盖 > settings 默认 > config 默认。"""
    base = POLICIES[_policy_name(settings_row, audit, skill_category)]
    analyzers = list(base.analyzers)

    regex_enabled = getattr(settings_row, "regex_enabled", True)
    if not regex_enabled and not settings.ai_policies_regex_enabled:
        regex_enabled = False
    if not regex_enabled and "regex" in analyzers:
        analyzers.remove("regex")

    # LLM 共识仅在 llm_review_enabled 且配置了模型时才参与
    llm_review_enabled = bool(getattr(settings_row, "llm_review_enabled", False))
    if not llm_review_enabled and "llm_consensus" in analyzers:
        analyzers.remove("llm_consensus")

    # llm_consensus_runs：settings 表 >0 覆盖 preset，否则用 preset 默认
    consensus_runs = base.llm_consensus_runs
    settings_runs = int(getattr(settings_row, "llm_consensus_runs", 0) or 0)
    if settings_runs > 0:
        consensus_runs = settings_runs

    return PolicySpec(
        name=base.name,
        analyzers=tuple(analyzers),
        fail_on_severity=base.fail_on_severity,
        llm_consensus_runs=consensus_runs,
    )
