"""Analyzer 注册表（S2）。

static 扫描是编排器内置基线（始终先跑），不在此注册。
policy.analyzers 列出可选 analyzer（regex / llm_consensus）。
"""

import logging

from services.ai_policies_analyzers.base import Analyzer
from services.ai_policies_analyzers.llm_consensus import LlmConsensusAnalyzer
from services.ai_policies_analyzers.regex import RegexAnalyzer
from services.ai_policies_policies import PolicySpec

logger = logging.getLogger(__name__)

REGISTRY: dict[str, type[Analyzer]] = {
    "regex": RegexAnalyzer,
    "llm_consensus": LlmConsensusAnalyzer,
}


def get_analyzers(policy: PolicySpec) -> list[Analyzer]:
    """按 policy 解析启用的 analyzer 实例（跳过未知名）。"""
    instances: list[Analyzer] = []
    for name in policy.analyzers:
        factory = REGISTRY.get(name)
        if not factory:
            logger.warning("unknown analyzer in policy %s: %s", policy.name, name)
            continue
        instances.append(factory())
    return instances
