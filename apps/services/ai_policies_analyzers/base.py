"""Analyzer 协议与上下文（S2）。

两种 phase：
- "raw"：扫描阶段，产出原始 finding 列表（合并后统一 normalize/classify/aggregate）。
- "review"：聚合后阶段，对已分组 findings 做复核（LLM 共识），产出 review dict。

static 扫描是编排器内置基线（始终先跑），不在本包内。
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from models.db import AiPoliciesAudit, AiPoliciesSettings, Skill, SkillVersion
from services.ai_policies_policies import PolicySpec


@dataclass
class AnalyzerContext:
    audit: AiPoliciesAudit
    zip_path: str
    target: Skill | SkillVersion | None
    settings_row: AiPoliciesSettings
    category_labels: dict[str, str]
    session: AsyncSession
    policy: PolicySpec
    # review phase 使用：聚合后的 findings（已 classify/aggregate/score）
    findings_so_far: list[dict] = field(default_factory=list)


@dataclass
class AnalyzerResult:
    analyzer: str
    findings: list[dict] = field(default_factory=list)  # raw phase 产出
    review: dict | None = None  # review phase 产出（LLM 共识）
    raw: dict = field(default_factory=dict)  # 存档进 raw_report
    version: str = ""
    error: str | None = None  # 单 analyzer 失败不阻断整体


@runtime_checkable
class Analyzer(Protocol):
    name: str
    phase: str  # "raw" | "review"

    async def analyze(self, ctx: AnalyzerContext) -> AnalyzerResult: ...
