"""Skill content parsing — ZIP → SKILL.md → frontmatter/summary/full + SHA-256 hashes.

This service is stateless and has no DB dependency. It is called during
version creation (write-time) so that queries (read-time) incur zero parsing cost.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)

SUMMARY_MAX_LINES = 30


@dataclass
class ParsedSkillContent:
    frontmatter: dict = field(default_factory=dict)
    summary_text: str = ""
    full_content: str = ""
    composite_hash: str = ""
    file_hashes: dict[str, dict] = field(default_factory=dict)


# ─── ZIP extraction ────────────────────────────────────────────────────────


def _find_skill_md_content(zip_bytes: bytes) -> tuple[str, str] | None:
    """Return (relative_path, raw_content) of SKILL.md inside the ZIP, or None."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # 1. Exact match at root
            for name in zf.namelist():
                if name == "SKILL.md":
                    return name, zf.read(name).decode("utf-8", errors="replace")

            # 2. Case-insensitive root match
            for name in zf.namelist():
                if name.upper() == "SKILL.MD":
                    return name, zf.read(name).decode("utf-8", errors="replace")

            # 3. SKILL.md anywhere in subdirectory (first match)
            for name in zf.namelist():
                if name.lower().endswith("skill.md"):
                    return name, zf.read(name).decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        logger.warning("Invalid ZIP file passed to content parser")
    return None


# ─── SKILL.md parsing ─────────────────────────────────────────────────────


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_skill_md(raw: str) -> tuple[dict, str]:
    """Parse SKILL.md into (frontmatter_dict, body_text).

    Supports standard YAML frontmatter delimited by ``---``.
    Falls back to extracting name from H1 and description from first paragraph.
    """
    frontmatter: dict = {}

    match = _FRONTMATTER_RE.match(raw)
    if match:
        try:
            parsed = yaml.safe_load(match.group(1))
            if isinstance(parsed, dict):
                frontmatter = parsed
        except yaml.YAMLError:
            logger.warning("Failed to parse YAML frontmatter, treating as plain text")
            for line in match.group(1).split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    frontmatter[k.strip()] = v.strip().strip("\"'")
        body = raw[match.end() :]
    else:
        body = raw

    # Fallback: extract name from H1 if not in frontmatter
    if "name" not in frontmatter:
        h1 = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if h1:
            frontmatter["name"] = h1.group(1).strip()

    # Fallback: extract description from first paragraph
    if "description" not in frontmatter:
        paragraph_lines: list[str] = []
        in_paragraph = False
        for line in body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                if in_paragraph:
                    break
                continue
            if not stripped:
                if in_paragraph:
                    break
                continue
            if stripped.startswith("```"):
                if in_paragraph:
                    break
                continue
            in_paragraph = True
            paragraph_lines.append(stripped)
        if paragraph_lines:
            frontmatter["description"] = " ".join(paragraph_lines)[:500]

    return frontmatter, body


def _extract_summary(body: str, max_lines: int = SUMMARY_MAX_LINES) -> str:
    """Return the first paragraph of the body, skipping leading headings."""
    lines = body.split("\n")
    # Skip leading blank lines and ATX headings (# ## ### …)
    idx = 0
    while idx < len(lines) and (
        not lines[idx].strip() or lines[idx].lstrip().startswith("#")
    ):
        idx += 1
    selected: list[str] = []
    for line in lines[idx : idx + max_lines]:
        if not line.strip() and selected:
            break
        selected.append(line)
    return "\n".join(selected).strip()


# ─── Hash computation ─────────────────────────────────────────────────────


def _compute_hashes(zip_bytes: bytes) -> tuple[str, dict[str, dict]]:
    """Compute per-file SHA-256/size and a composite hash sorted by path.

    Returns (composite_hash, {relative_path: {"sha256": hex, "size": bytes}}).

    Manifest value carries sha256 + size only; ``content_type`` / ``category``
    are filled by skill_protocol_service.validate_skill_protocol. composite_hash
    formula is unchanged (path:sha pairs) so S9 drift comparison stays stable
    across the value-structure upgrade.
    """
    file_hashes: dict[str, dict] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in sorted(zf.namelist()):
                if name.endswith("/"):
                    continue
                data = zf.read(name)
                file_hashes[name] = {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
    except zipfile.BadZipFile:
        logger.warning("Invalid ZIP file passed to hash computation")

    if not file_hashes:
        return "", {}

    composite_input = "".join(
        f"{path}:{entry['sha256']}" for path, entry in sorted(file_hashes.items())
    )
    composite_hash = hashlib.sha256(composite_input.encode()).hexdigest()
    return composite_hash, file_hashes


# ─── Public API ────────────────────────────────────────────────────────────


def parse_skill_zip(zip_bytes: bytes) -> ParsedSkillContent:
    """Parse Skill ZIP: find SKILL.md, extract content, compute hashes."""
    result = ParsedSkillContent()

    # Hashes — always computed (even if no SKILL.md)
    result.composite_hash, result.file_hashes = _compute_hashes(zip_bytes)

    found = _find_skill_md_content(zip_bytes)
    if found is None:
        logger.info("No SKILL.md found in ZIP")
        return result

    _skill_md_path, raw_content = found
    fm, body = _parse_skill_md(raw_content)
    result.frontmatter = fm
    result.summary_text = _extract_summary(body)
    result.full_content = body.strip()

    return result


def apply_parsed_to_version(version: object, parsed: ParsedSkillContent) -> None:
    """Write parsed content fields onto a SkillVersion ORM instance."""
    version.frontmatter = parsed.frontmatter
    version.summary_text = parsed.summary_text
    version.full_content = parsed.full_content
    version.composite_hash = parsed.composite_hash
    version.file_hashes = parsed.file_hashes


# ─── 单名称契约：zip 内 SKILL.md name 重写（DB → markdown 方向） ────────────


# 仅匹配 frontmatter 块内顶层（列 0）的 name: 行，缩进的嵌套 name 不受影响
_NAME_LINE_RE = re.compile(r"^name:[ \t]*.*$", re.MULTILINE)


def replace_frontmatter_name(raw: str, new_name: str) -> str:
    """SKILL.md 全文里替换/插入 frontmatter name 键，其余内容不动。

    - 有顶层 ``name:`` 行 → 行级替换（首个）
    - 有 frontmatter 块但无 name 键（H1 回填场景源文无键）→ 开块 ``---`` 后插一行
    - 无 frontmatter 块 → 头部构造块
    """
    match = _FRONTMATTER_RE.match(raw)
    if match is None:
        return f"---\nname: {new_name}\n---\n{raw}"
    block = match.group(1)
    if _NAME_LINE_RE.search(block):
        block = _NAME_LINE_RE.sub(f"name: {new_name}", block, count=1)
    else:
        block = f"name: {new_name}\n{block}"
    return raw[: match.start(1)] + block + raw[match.end(1) :]


@dataclass
class ZipRewriteResult:
    new_bytes: bytes
    skill_md_path: str  # zip 内 SKILL.md 条目路径（重写前）
    root_dir_renamed: bool  # 顶层目录是否已同步改为 new_name


def rewrite_zip_skill_name(
    zip_bytes: bytes, new_name: str, *, rename_root_dir: bool = True
) -> ZipRewriteResult | None:
    """重写 zip 内 SKILL.md 的 frontmatter name，可选把顶层目录同步改为 new_name。

    - 保留各条目 date_time / external_attr（权限位），DEFLATE 重打包；目录条目
      不单独写出（由文件条目路径隐式重建）。
    - 顶层目录改名仅当 SKILL.md 位于子目录且目录名 ≠ new_name（对齐生态约定
      「zip 顶层目录 = name」，消灭 name.dir_mismatch warning）。
    - 包内无 SKILL.md → 返回 None（调用方决定报错）。
    """
    found = _find_skill_md_content(zip_bytes)
    if found is None:
        return None
    skill_md_path, raw_content = found
    new_md = replace_frontmatter_name(raw_content, new_name).encode("utf-8")

    prefix = ""
    idx = skill_md_path.rfind("/")
    if idx != -1:
        prefix = skill_md_path[: idx + 1]
    rename = bool(rename_root_dir and prefix and prefix[:-1] != new_name)

    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as src, zipfile.ZipFile(
        buf, "w", zipfile.ZIP_DEFLATED
    ) as dst:
        for info in src.infolist():
            if info.is_dir():
                continue
            data = src.read(info.filename)
            entry_name = info.filename
            if entry_name == skill_md_path:
                data = new_md
            if rename and entry_name.startswith(prefix):
                entry_name = f"{new_name}/{entry_name[len(prefix):]}"
            zi = zipfile.ZipInfo(entry_name, date_time=info.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            dst.writestr(zi, data)
    return ZipRewriteResult(buf.getvalue(), skill_md_path, rename)
