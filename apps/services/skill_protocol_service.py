r"""Skill 协议合规校验（模块 S1）。

在前序 04 的 ``skill_content_service`` 解析结果之上叠加协议合规校验层：
SKILL.md 存在性、frontmatter 必填字段（name kebab-case、description）、
目录约定识别（references/scripts/assets）与 manifest 文件清单补充。

校验规则参考 skillhub（``D:\project\demo\skillhub``）：
- ``LabelSlugValidator.java``：kebab 正则 + 禁 ``--``
- ``SkillMetadataParser.java``：必填 name/description

本服务只做协议语义校验；物理包安全（zip slip / 大小 / 扩展名白名单 /
magic bytes）属 S5 范围，不在此处。

草稿容错模型：errors 不阻断注册，由 ``skill_service.activate_version`` 门控。
"""

from __future__ import annotations

import logging
import mimetypes
import re
from dataclasses import dataclass, field

from services.skill_content_service import ParsedSkillContent

logger = logging.getLogger(__name__)

# kebab-case：小写字母/数字，连字符分隔，不能 ``--``，长度 1-64
# 参考 skillhub LabelSlugValidator（^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ + 禁双连字符）
_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_NAME_MAX_LENGTH = 64
_DESCRIPTION_SOFT_MAX = 200

_CATEGORY_ROOT = "root"
_CATEGORY_REFERENCES = "references"
_CATEGORY_SCRIPTS = "scripts"
_CATEGORY_ASSETS = "assets"
_CATEGORY_OTHER = "other"


@dataclass
class ProtocolIssue:
    severity: str  # "error" | "warning"
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass
class ProtocolValidationResult:
    valid: bool
    errors: list[ProtocolIssue] = field(default_factory=list)
    warnings: list[ProtocolIssue] = field(default_factory=list)
    manifest: dict[str, dict] = field(default_factory=dict)

    def to_storage_list(self) -> list[dict]:
        """合并 errors + warnings 供 protocol_errors JSONB 列存储。"""
        return [i.to_dict() for i in (self.errors + self.warnings)]


def _has_skill_md(parsed: ParsedSkillContent) -> bool:
    """zip 内是否存在 SKILL.md（大小写不敏感，根或子目录均可）。"""
    for path in parsed.file_hashes:
        if path.lower().endswith("skill.md"):
            return True
    return False


def _category_for_path(path: str) -> str:
    lower = path.lower()
    if lower == "skill.md" or lower.endswith("/skill.md"):
        return _CATEGORY_ROOT
    if "/" in path:
        top = path.split("/", 1)[0].lower()
        if top == _CATEGORY_REFERENCES:
            return _CATEGORY_REFERENCES
        if top == _CATEGORY_SCRIPTS:
            return _CATEGORY_SCRIPTS
        if top == _CATEGORY_ASSETS:
            return _CATEGORY_ASSETS
    return _CATEGORY_OTHER


def _content_type_for_path(path: str) -> str:
    guess, _ = mimetypes.guess_type(path)
    return guess or "application/octet-stream"


def _build_manifest(parsed: ParsedSkillContent) -> dict[str, dict]:
    """在 file_hashes {path:{sha256,size}} 基础上补 content_type/category。"""
    manifest: dict[str, dict] = {}
    for path, entry in parsed.file_hashes.items():
        manifest[path] = {
            "sha256": entry.get("sha256", ""),
            "size": entry.get("size", 0),
            "content_type": _content_type_for_path(path),
            "category": _category_for_path(path),
        }
    return manifest


def _shared_top_dir(paths: list[str]) -> str | None:
    """所有文件是否共享同一顶层目录；是则返回该目录名，否则 None。"""
    tops = {p.split("/", 1)[0] for p in paths if "/" in p}
    if len(tops) == 1:
        return next(iter(tops))
    return None


def validate_skill_protocol(parsed: ParsedSkillContent) -> ProtocolValidationResult:
    """校验解析结果，返回 (valid, errors, warnings, manifest)。"""
    errors: list[ProtocolIssue] = []
    warnings: list[ProtocolIssue] = []
    manifest = _build_manifest(parsed)

    # 1. SKILL.md 存在性
    if not _has_skill_md(parsed):
        errors.append(
            ProtocolIssue(
                "error",
                "skill_md.missing",
                "包根目录缺少 SKILL.md，无法被客户端 agent 识别",
            )
        )

    frontmatter = parsed.frontmatter or {}
    name = str(frontmatter.get("name", "")).strip()
    description = str(frontmatter.get("description", "")).strip()

    # 2. name 必填 + kebab-case
    if not name:
        errors.append(
            ProtocolIssue(
                "error",
                "name.missing",
                "SKILL.md frontmatter 缺少必填字段 name",
            )
        )
    elif len(name) > _NAME_MAX_LENGTH:
        errors.append(
            ProtocolIssue(
                "error",
                "name.too_long",
                f"name 长度不能超过 {_NAME_MAX_LENGTH} 个字符",
            )
        )
    elif "--" in name:
        errors.append(
            ProtocolIssue(
                "error",
                "name.double_hyphen",
                "name 不能包含连续连字符 '--'",
            )
        )
    elif not _NAME_PATTERN.match(name):
        errors.append(
            ProtocolIssue(
                "error",
                "name.not_kebab",
                f"name 必须为 kebab-case（仅小写字母、数字、单连字符），当前 '{name}'",
            )
        )

    # 3. description 必填 + 软长度
    if not description:
        errors.append(
            ProtocolIssue(
                "error",
                "description.missing",
                "SKILL.md frontmatter 缺少必填字段 description",
            )
        )
    elif len(description) > _DESCRIPTION_SOFT_MAX:
        warnings.append(
            ProtocolIssue(
                "warning",
                "description.too_long",
                f"description 建议不超过 {_DESCRIPTION_SOFT_MAX} 字，"
                f"当前 {len(description)} 字",
            )
        )

    # 4. name 与目录名一致性（warning，仅当能确定唯一顶层目录时）
    paths = list(parsed.file_hashes.keys())
    if name and len(paths) > 1:
        top = _shared_top_dir(paths)
        if top and top != name:
            warnings.append(
                ProtocolIssue(
                    "warning",
                    "name.dir_mismatch",
                    f"name '{name}' 与包顶层目录 '{top}' 不一致，"
                    "建议对齐以便生态客户端按目录加载",
                )
            )

    # 5. 非标准目录识别（warning）
    for path in paths:
        cat = manifest[path]["category"]
        if cat == _CATEGORY_OTHER and "/" in path:
            top = path.split("/", 1)[0]
            if top.lower() not in {
                _CATEGORY_REFERENCES,
                _CATEGORY_SCRIPTS,
                _CATEGORY_ASSETS,
            }:
                warnings.append(
                    ProtocolIssue(
                        "warning",
                        "dir.non_standard",
                        f"非标准目录 '{top}/'，建议使用 references/ scripts/ assets/",
                    )
                )
                break

    return ProtocolValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        manifest=manifest,
    )
