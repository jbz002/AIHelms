"""Skill content parsing service — ZIP → SKILL.md → frontmatter/summary/full + SHA-256 hashes.

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
from typing import BinaryIO

import yaml

logger = logging.getLogger(__name__)

SUMMARY_MAX_LINES = 30


@dataclass
class ParsedSkillContent:
    frontmatter: dict = field(default_factory=dict)
    summary_text: str = ""
    full_content: str = ""
    composite_hash: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)


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
        body = raw[match.end():]
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
    """Return the first *max_lines* of the body, trimmed to the first blank line."""
    lines = body.split("\n")
    selected: list[str] = []
    for line in lines[:max_lines]:
        if not line.strip() and selected:
            break
        selected.append(line)
    return "\n".join(selected).strip()


# ─── Hash computation ─────────────────────────────────────────────────────


def _compute_hashes(zip_bytes: bytes) -> tuple[str, dict[str, str]]:
    """Compute per-file SHA-256 and a composite hash sorted by path.

    Returns (composite_hash, {relative_path: sha256_hex}).
    """
    file_hashes: dict[str, str] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in sorted(zf.namelist()):
                if name.endswith("/"):
                    continue
                data = zf.read(name)
                file_hashes[name] = hashlib.sha256(data).hexdigest()
    except zipfile.BadZipFile:
        logger.warning("Invalid ZIP file passed to hash computation")

    if not file_hashes:
        return "", {}

    composite_input = "".join(f"{path}:{sha}" for path, sha in sorted(file_hashes.items()))
    composite_hash = hashlib.sha256(composite_input.encode()).hexdigest()
    return composite_hash, file_hashes


# ─── Public API ────────────────────────────────────────────────────────────


def parse_skill_zip(zip_bytes: bytes) -> ParsedSkillContent:
    """Parse a Skill ZIP: find SKILL.md, extract frontmatter/summary/full, compute hashes."""
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
