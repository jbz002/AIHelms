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


def _build_manifest(
    parsed: ParsedSkillContent, root_prefix: str = ""
) -> dict[str, dict]:
    """在 file_hashes {path:{sha256,size}} 基础上补 content_type/category。

    category 按「相对于 skill 根」的路径判定：root_prefix 是 SKILL.md 所在
    目录前缀（如 Anthropic 官方包解出的 ``pdf/``），需先剥离再分类，否则
    外层目录会被误判为非标准子目录。manifest 键仍保留 zip 内原始路径。
    """
    manifest: dict[str, dict] = {}
    for path, entry in parsed.file_hashes.items():
        rel = _strip_root_prefix(path, root_prefix)
        manifest[path] = {
            "sha256": entry.get("sha256", ""),
            "size": entry.get("size", 0),
            "content_type": _content_type_for_path(path),
            "category": _category_for_path(rel),
        }
    return manifest


def _strip_root_prefix(path: str, root_prefix: str) -> str:
    """剥除 skill 根目录前缀，返回相对路径；无前缀或不匹配则原样返回。"""
    if root_prefix and path.startswith(root_prefix):
        return path[len(root_prefix) :]
    return path


def _skill_root_prefix(paths: list[str]) -> str:
    """SKILL.md 所在目录前缀（含尾斜杠）；SKILL.md 在包根则返回 ``''``。

    用于区分「包外层目录」（如 ``pdf.zip`` 解出的 ``pdf/``，是 skill 根）
    与「内容子目录」（references/scripts/assets）。大小写不敏感定位
    SKILL.md，取其最后一级目录。
    """
    for p in paths:
        if p.lower().endswith("skill.md"):
            idx = p.rfind("/")
            return p[: idx + 1] if idx != -1 else ""
    return ""


def validate_skill_protocol(parsed: ParsedSkillContent) -> ProtocolValidationResult:
    """校验解析结果，返回 (valid, errors, warnings, manifest)。"""
    errors: list[ProtocolIssue] = []
    warnings: list[ProtocolIssue] = []

    paths = list(parsed.file_hashes.keys())
    # SKILL.md 所在目录即 skill 根（如 ``pdf/``）；分类与子目录校验均相对它
    root_prefix = _skill_root_prefix(paths)
    manifest = _build_manifest(parsed, root_prefix)

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

    # 4. name 与包外层目录一致性（仅当 SKILL.md 位于子目录时）
    if name and root_prefix:
        root_dir = root_prefix[:-1]
        if root_dir != name:
            warnings.append(
                ProtocolIssue(
                    "warning",
                    "name.dir_mismatch",
                    f"name '{name}' 与包顶层目录 '{root_dir}' 不一致，"
                    "建议对齐以便生态客户端按目录加载",
                )
            )

    # 5. 非标准子目录识别（warning，相对 skill 根）
    flagged: set[str] = set()
    _standard = {_CATEGORY_REFERENCES, _CATEGORY_SCRIPTS, _CATEGORY_ASSETS}
    for path in paths:
        rel = _strip_root_prefix(path, root_prefix)
        if "/" not in rel:
            continue
        top = rel.split("/", 1)[0]
        if top.lower() in _standard or top in flagged:
            continue
        flagged.add(top)
        warnings.append(
            ProtocolIssue(
                "warning",
                "dir.non_standard",
                f"非标准目录 '{top}/'，建议使用 references/ scripts/ assets/",
            )
        )

    return ProtocolValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        manifest=manifest,
    )
