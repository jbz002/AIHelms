"""LLM 共识 analyzer（S2）。

对聚合后的 findings 跑 N 次 run_llm_review，按 group_id 多数表决合并 finding_reviews，
降单次误报。N=1 时退化为单次（等价旧行为）。redline 由 apply_finding_reviews 短路保留。
"""

import asyncio
import logging
from collections import Counter

from services import ai_policies_llm
from services.ai_policies_analyzers.base import (
    AnalyzerContext,
    AnalyzerResult,
)
from services.ai_policies_denoise import SEVERITY_RANK

logger = logging.getLogger(__name__)

_TYPE_PRIORITY = {"true_risk": 3, "review_note": 2, "false_positive": 1}


def _vote_key(review: dict) -> tuple[str, str]:
    return (
        str(review.get("finding_type") or "").strip(),
        str(review.get("effective_severity") or "").strip().lower(),
    )


def _merge_finding_reviews(runs: list[dict]) -> tuple[list[dict], float]:
    """按 group_id 多数表决。返回 (merged_reviews, disagreement_rate)。"""
    per_group: dict[str, list[tuple[str, str]]] = {}
    for run in runs:
        for review in run.get("finding_reviews") or []:
            if not isinstance(review, dict):
                continue
            group_id = str(review.get("group_id") or "")
            if not group_id:
                continue
            per_group.setdefault(group_id, []).append(_vote_key(review))

    merged: list[dict] = []
    disagreements = 0
    for group_id, votes in per_group.items():
        if not votes:
            continue
        majority = len(votes) // 2 + 1
        counter = Counter(votes)
        top_pair, top_count = counter.most_common(1)[0]
        if top_count >= majority:
            chosen_type, chosen_sev = top_pair
        else:
            disagreements += 1
            chosen_type, chosen_sev = _most_conservative(votes)
        merged.append(
            {
                "group_id": group_id,
                "finding_type": chosen_type,
                "effective_severity": chosen_sev,
            }
        )
    total_groups = len(per_group)
    rate = (disagreements / total_groups) if total_groups else 0.0
    return merged, rate


def _most_conservative(votes: list[tuple[str, str]]) -> tuple[str, str]:
    """无多数时取最保守：severity 最高；同 severity 取 type 优先级高者。"""

    def sort_key(item: tuple[str, str]) -> tuple[int, int]:
        ftype, sev = item
        return (SEVERITY_RANK.get(sev, 0), _TYPE_PRIORITY.get(ftype, 0))

    return max(votes, key=sort_key)


class LlmConsensusAnalyzer:
    name = "llm_consensus"
    phase = "review"

    async def analyze(self, ctx: AnalyzerContext) -> AnalyzerResult:
        model_id = ctx.settings_row.llm_review_model_id
        runs_target = max(1, int(ctx.policy.llm_consensus_runs or 1))
        timeout = ctx.settings.ai_policies_llm_consensus_timeout_seconds

        completed: list[dict] = []
        last_error = ""
        model_name = ""
        for _ in range(runs_target):
            try:
                run = await asyncio.wait_for(
                    ai_policies_llm.run_llm_review(
                        ctx.session,
                        model_id,
                        ctx.audit,
                        ctx.findings_so_far,
                        ctx.category_labels,
                        ctx.zip_path,
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                last_error = "LLM 共识单次审查超时"
                logger.warning(
                    "llm consensus run timed out: audit_id=%s", ctx.audit.audit_id
                )
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.exception(
                    "llm consensus run failed: audit_id=%s", ctx.audit.audit_id
                )
                continue
            if run.get("status") == "completed":
                completed.append(run)
                model_name = model_name or str(run.get("model") or "")
            elif run.get("status") == "skipped":
                # 模型/Key 不可用，继续后续 run 也无意义
                return AnalyzerResult(
                    analyzer=self.name,
                    review=run,
                    raw={
                        "consensus_runs": 0,
                        "skip_reason": run.get("message") or "skipped",
                    },
                    version=model_name,
                )

        if not completed:
            return AnalyzerResult(
                analyzer=self.name,
                review={
                    "status": "failed",
                    "message": last_error or "LLM 共识审查无可用结果",
                },
                raw={"consensus_runs": 0},
                version=model_name,
                error=last_error or None,
            )

        merged_reviews, disagreement_rate = _merge_finding_reviews(completed)
        base = completed[0]
        consensus = {
            "status": "completed",
            "model": model_name or base.get("model"),
            "consensus_runs": len(completed),
            "consensus_target": runs_target,
            "consensus_disagreement_rate": round(disagreement_rate, 3),
            "consensus": (
                "majority"
                if len(completed) >= 2 and disagreement_rate == 0.0
                else "merged"
            ),
            "finding_reviews": merged_reviews,
            "category_reviews": base.get("category_reviews") or [],
            "intent_analysis": base.get("intent_analysis") or {},
            "overall_judgement": base.get("overall_judgement") or "",
        }
        return AnalyzerResult(
            analyzer=self.name,
            review=consensus,
            raw={
                "consensus_runs": len(completed),
                "consensus_target": runs_target,
                "consensus_disagreement_rate": round(disagreement_rate, 3),
            },
            version=model_name,
        )
