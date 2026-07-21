"""LLM 共识多数表决单元测试（S2）。纯函数，不依赖 DB/LLM。"""

from services.ai_policies_analyzers.llm_consensus import (
    _merge_finding_reviews,
    _most_conservative,
)


def test_majority_vote_adopts_plurality_pair():
    runs = [
        {
            "finding_reviews": [
                {
                    "group_id": "g1",
                    "finding_type": "true_risk",
                    "effective_severity": "high",
                }
            ]
        },
        {
            "finding_reviews": [
                {
                    "group_id": "g1",
                    "finding_type": "true_risk",
                    "effective_severity": "high",
                }
            ]
        },
        {
            "finding_reviews": [
                {
                    "group_id": "g1",
                    "finding_type": "false_positive",
                    "effective_severity": "low",
                }
            ]
        },
    ]
    merged, rate = _merge_finding_reviews(runs)
    assert len(merged) == 1
    assert merged[0]["group_id"] == "g1"
    assert merged[0]["finding_type"] == "true_risk"
    assert merged[0]["effective_severity"] == "high"
    assert rate == 0.0


def test_no_majority_falls_back_conservative_severity():
    runs = [
        {
            "finding_reviews": [
                {
                    "group_id": "g1",
                    "finding_type": "true_risk",
                    "effective_severity": "medium",
                }
            ]
        },
        {
            "finding_reviews": [
                {
                    "group_id": "g1",
                    "finding_type": "false_positive",
                    "effective_severity": "low",
                }
            ]
        },
    ]
    merged, rate = _merge_finding_reviews(runs)
    assert merged[0]["effective_severity"] == "medium"
    assert merged[0]["finding_type"] == "true_risk"
    assert rate == 1.0


def test_most_conservative_picks_highest_severity_then_type_priority():
    votes = [
        ("false_positive", "low"),
        ("true_risk", "medium"),
        ("review_note", "high"),
    ]
    ftype, sev = _most_conservative(votes)
    assert sev == "high"
    assert ftype == "review_note"


def test_most_conservative_same_severity_picks_higher_type_priority():
    votes = [("false_positive", "high"), ("true_risk", "high")]
    ftype, _ = _most_conservative(votes)
    assert ftype == "true_risk"


def test_empty_runs_return_empty():
    merged, rate = _merge_finding_reviews([])
    assert merged == []
    assert rate == 0.0


def test_multiple_groups_voted_independently():
    runs = [
        {
            "finding_reviews": [
                {
                    "group_id": "g1",
                    "finding_type": "true_risk",
                    "effective_severity": "high",
                },
                {
                    "group_id": "g2",
                    "finding_type": "false_positive",
                    "effective_severity": "low",
                },
            ]
        },
        {
            "finding_reviews": [
                {
                    "group_id": "g1",
                    "finding_type": "true_risk",
                    "effective_severity": "high",
                },
                {
                    "group_id": "g2",
                    "finding_type": "true_risk",
                    "effective_severity": "medium",
                },
            ]
        },
    ]
    merged, _ = _merge_finding_reviews(runs)
    by_group = {m["group_id"]: m for m in merged}
    assert by_group["g1"]["finding_type"] == "true_risk"
    # g2 disagree → conservative: medium > low
    assert by_group["g2"]["effective_severity"] == "medium"
