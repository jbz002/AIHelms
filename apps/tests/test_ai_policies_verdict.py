"""Verdict 4 级聚合单元测试（S2）。纯函数，不依赖 DB/中间件。"""

from services.ai_policies_denoise import ScoreResult
from services.ai_policies_verdict import (
    VERDICT_BLOCKED,
    VERDICT_DANGEROUS,
    VERDICT_SAFE,
    VERDICT_SUSPICIOUS,
    aggregate,
    decision_for,
)


def _score(severity: str, risk_score: int = 0) -> ScoreResult:
    return ScoreResult(
        severity=severity,
        risk_score=risk_score,
        decision="",
        high_risk_count=0,
        must_review_count=0,
        findings_count=0,
    )


def test_redline_forces_blocked_regardless_of_policy():
    assert aggregate(_score("low"), "critical", has_redline=True) == VERDICT_BLOCKED


def test_critical_strict_fail_on_medium_blocked():
    assert aggregate(_score("critical"), "medium", has_redline=False) == VERDICT_BLOCKED


def test_high_balanced_fail_on_high_blocked():
    assert aggregate(_score("high"), "high", has_redline=False) == VERDICT_BLOCKED


def test_high_permissive_fail_on_critical_dangerous():
    assert aggregate(_score("high"), "critical", has_redline=False) == VERDICT_DANGEROUS


def test_medium_permissive_suspicious():
    assert (
        aggregate(_score("medium"), "critical", has_redline=False) == VERDICT_SUSPICIOUS
    )


def test_risk_score_only_suspicious():
    assert (
        aggregate(_score("none", risk_score=10), "critical", has_redline=False)
        == VERDICT_SUSPICIOUS
    )


def test_clean_safe():
    assert aggregate(_score("none"), "medium", has_redline=False) == VERDICT_SAFE


def test_decision_mapping_covers_four_verdicts():
    assert decision_for(VERDICT_SAFE) == "passed"
    assert decision_for(VERDICT_SUSPICIOUS) == "attention_required"
    assert decision_for(VERDICT_DANGEROUS) == "high_risk"
    assert decision_for(VERDICT_BLOCKED) == "failed"
