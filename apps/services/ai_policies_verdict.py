"""Verdict 4 级聚合（S2）。

聚合规则（权威）：
1. 任一 redline=true → BLOCKED（强制，与 policy 无关）
2. 否则 max_severity >= fail_on_severity → BLOCKED
3. 否则 max_severity ∈ {critical, high} → DANGEROUS
4. 否则 max_severity == medium 或 risk_score > 0 → SUSPICIOUS
5. 否则 → SAFE

Verdict 映射到现有 decision，激活门控（_ACTIVATE_ALLOWED_DECISIONS）不改。
"""

from services.ai_policies_denoise import SEVERITY_RANK, ScoreResult

VERDICT_SAFE = "SAFE"
VERDICT_SUSPICIOUS = "SUSPICIOUS"
VERDICT_DANGEROUS = "DANGEROUS"
VERDICT_BLOCKED = "BLOCKED"

VERDICT_TO_DECISION: dict[str, str] = {
    VERDICT_SAFE: "passed",
    VERDICT_SUSPICIOUS: "attention_required",
    VERDICT_DANGEROUS: "high_risk",
    VERDICT_BLOCKED: "failed",
}


def aggregate(
    score_result: ScoreResult,
    fail_on_severity: str,
    has_redline: bool,
) -> str:
    max_severity = (score_result.severity or "").lower()
    fail_rank = SEVERITY_RANK.get((fail_on_severity or "").lower(), 0)
    max_rank = SEVERITY_RANK.get(max_severity, 0)

    if has_redline:
        return VERDICT_BLOCKED
    if fail_rank > 0 and max_rank >= fail_rank:
        return VERDICT_BLOCKED
    if max_severity in {"critical", "high"}:
        return VERDICT_DANGEROUS
    if max_severity == "medium" or score_result.risk_score > 0:
        return VERDICT_SUSPICIOUS
    return VERDICT_SAFE


def decision_for(verdict: str) -> str:
    return VERDICT_TO_DECISION.get(verdict, "passed")
