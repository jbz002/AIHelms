"""Regex signatures analyzer（S2）。

加载 apps/security_rules/signatures.yaml（mtime 热加载），扫 Skill zip 内文本文件，
产 raw finding（统一进 _normalize_finding 走 classify/redline/aggregate）。
"""

import fnmatch
import hashlib
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from core.config import settings
from services.ai_policies_analyzers.base import (
    AnalyzerContext,
    AnalyzerResult,
)

logger = logging.getLogger(__name__)

# 9 分类 → 现有 risk_catalog AST 编码（data_exfiltration 走 AST10，对齐 _map_category）
CATEGORY_MAP: dict[str, str] = {
    "prompt_injection": "AST05",
    "command_injection": "AST06",
    "data_exfiltration": "AST10",
    "unauthorized_tool_use": "AST03",
    "obfuscation": "AST06",
    "hardcoded_secrets": "AST02",
    "social_engineering": "AST01",
    "resource_abuse": "AST03",
    "policy_violation": "AST04",
}

SEVERITY_CONFIDENCE: dict[str, int] = {
    "critical": 95,
    "high": 80,
    "medium": 60,
    "low": 30,
    "info": 10,
}

MAX_FILE_BYTES = 1024 * 1024  # 单文件 >1MB 跳过，避免扫 minified 资源


@dataclass(frozen=True)
class CompiledRule:
    id: str
    category: str  # AST 编码
    raw_category: str
    severity: str
    pattern_text: str
    pattern: Any  # re.Pattern
    file_types: tuple[str, ...]
    title: str
    description: str
    remediation: str


# (path, mtime_ns, size) → (rules, version)
_RULES_CACHE: dict[tuple[str, int, int], tuple[list[CompiledRule], str]] = {}


def _resolve_path() -> Path:
    configured = settings.ai_policies_signatures_path
    candidate = Path(configured)
    if not candidate.is_absolute():
        # 相对 apps/ 工作目录解析（本文件位于 apps/services/ai_policies_analyzers/）
        candidate = Path(__file__).resolve().parents[2] / configured
    return candidate


def _compile_rule(raw: dict) -> CompiledRule | None:
    rule_id = str(raw.get("id") or "").strip()
    if not rule_id:
        logger.warning("regex rule missing id, skipped: %s", raw)
        return None
    if not rule_id.startswith("REG-"):
        rule_id = f"REG-{rule_id}"
    raw_category = str(raw.get("category") or "").strip().lower()
    category = (
        CATEGORY_MAP.get(raw_category) or str(raw.get("category") or "").strip().upper()
    )
    if not category.upper().startswith("AST"):
        category = "AST08"
    pattern_text = str(raw.get("pattern") or "")
    if not pattern_text:
        logger.warning("regex rule %s missing pattern, skipped", rule_id)
        return None
    import re

    try:
        pattern = re.compile(pattern_text, re.IGNORECASE | re.MULTILINE)
    except re.error as exc:
        logger.warning("regex rule %s invalid pattern: %s", rule_id, exc)
        return None
    file_types = tuple(
        str(ft).strip() for ft in (raw.get("file_types") or ["*"]) if str(ft).strip()
    )
    return CompiledRule(
        id=rule_id,
        category=category,
        raw_category=raw_category,
        severity=str(raw.get("severity") or "medium").lower(),
        pattern=pattern,
        pattern_text=pattern_text,
        file_types=file_types or ("*",),
        title=str(raw.get("title") or "").strip(),
        description=str(raw.get("description") or "").strip(),
        remediation=str(raw.get("remediation") or "").strip(),
    )


def load_rules(path: Path | None = None) -> tuple[list[CompiledRule], str]:
    """加载规则，mtime+size 双 key 缓存（进程内热加载，不重启）。"""
    path = path or _resolve_path()
    try:
        st = path.stat()
    except OSError:
        logger.warning("signatures.yaml not found: %s", path)
        return [], "unknown"
    key = (str(path), st.st_mtime_ns, st.st_size)
    cached = _RULES_CACHE.get(key)
    if cached:
        return cached
    try:
        with open(path, "r", encoding="utf-8") as fp:
            raw_text = fp.read()
        data = yaml.safe_load(raw_text) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.exception("signatures.yaml load failed: %s", exc)
        return [], "unknown"
    rules = [
        rule
        for rule in (_compile_rule(item) for item in data.get("rules") or [])
        if rule
    ]
    version = str(
        data.get("version") or hashlib.sha1(raw_text.encode("utf-8")).hexdigest()[:10]
    )
    _RULES_CACHE.clear()
    _RULES_CACHE[key] = (rules, version)
    return rules, version


def _file_matches(name: str, file_types: tuple[str, ...]) -> bool:
    base = name.split("/")[-1]
    return any(fnmatch.fnmatch(base, pattern) for pattern in file_types)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _snippet(text: str, start_line: int, span: int = 3) -> str:
    lines = text.splitlines()
    begin = max(0, start_line - 1)
    end = min(len(lines), begin + span)
    width = len(str(end if end else 1))
    return "\n".join(f"{idx + 1:>{width}} | {lines[idx]}" for idx in range(begin, end))


class RegexAnalyzer:
    name = "regex"
    phase = "raw"

    async def analyze(self, ctx: AnalyzerContext) -> AnalyzerResult:
        rules, version = load_rules()
        if not rules:
            return AnalyzerResult(
                analyzer=self.name, raw={"rule_count": 0}, version=version
            )
        findings: list[dict] = []
        try:
            with zipfile.ZipFile(ctx.zip_path) as zf:
                for info in zf.infolist():
                    if info.is_dir() or info.file_size > MAX_FILE_BYTES:
                        continue
                    file_name = info.filename.lstrip("/")
                    text = zf.read(info.filename).decode("utf-8", errors="ignore")
                    for rule in rules:
                        if not _file_matches(file_name, rule.file_types):
                            continue
                        for match in rule.pattern.finditer(text):
                            line = _line_number(text, match.start())
                            findings.append(
                                {
                                    "source": "regex",
                                    "id": rule.id,
                                    "severity": rule.severity.upper(),
                                    "category": rule.category,
                                    "pattern": rule.pattern_text,
                                    "tags": [],
                                    "confidence": SEVERITY_CONFIDENCE.get(
                                        rule.severity, 40
                                    ),
                                    "location": {
                                        "file": file_name,
                                        "start_line": line,
                                        "end_line": line,
                                    },
                                    "code_snippet": _snippet(text, line),
                                    "finding": match.group(0)[:240],
                                    "title": rule.title,
                                    "description": rule.description,
                                    "remediation": rule.remediation,
                                }
                            )
        except (zipfile.BadZipFile, OSError) as exc:
            logger.exception("regex analyzer zip read failed: %s", exc)
            return AnalyzerResult(analyzer=self.name, version=version, error=str(exc))
        return AnalyzerResult(
            analyzer=self.name,
            findings=findings,
            raw={"rule_count": len(rules), "match_count": len(findings)},
            version=version,
        )
