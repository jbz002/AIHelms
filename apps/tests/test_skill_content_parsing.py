"""Tests for skill_content_service — pure parsing, no DB required."""

import hashlib
import io
import zipfile

from services.skill_content_service import (
    ParsedSkillContent,
    _compute_hashes,
    _extract_summary,
    _parse_skill_md,
    apply_parsed_to_version,
    parse_skill_zip,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_zip(files: dict[str, str]) -> bytes:
    """Create a ZIP archive from {relative_path: content} dict."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _make_skill_md(frontmatter: str = "", body: str = "") -> str:
    if frontmatter:
        return f"---\n{frontmatter}\n---\n{body}"
    return body


# ─── Test SKILL.md parsing ─────────────────────────────────────────────────────


class TestParseSkillMd:
    def test_standard_frontmatter_and_body(self):
        content = _make_skill_md(
            frontmatter="name: my-skill\ndescription: A test skill\nversion: 1.0",
            body="\n# My Skill\n\nSome instructions here.",
        )
        fm, body = _parse_skill_md(content)
        assert fm["name"] == "my-skill"
        assert fm["description"] == "A test skill"
        assert "# My Skill" in body

    def test_missing_frontmatter_fallback_h1(self):
        content = "# Hello World\n\nThis is a description paragraph."
        fm, body = _parse_skill_md(content)
        assert fm["name"] == "Hello World"
        assert fm["description"] == "This is a description paragraph."

    def test_missing_frontmatter_fallback_paragraph(self):
        content = "First paragraph of text.\n\nSecond paragraph."
        fm, body = _parse_skill_md(content)
        # No H1 heading → name key not set in frontmatter
        assert "name" not in fm
        assert fm["description"] == "First paragraph of text."

    def test_empty_content(self):
        fm, body = _parse_skill_md("")
        assert fm == {}
        assert body == ""

    def test_frontmatter_overrides_h1(self):
        content = _make_skill_md(
            frontmatter="name: fm-name",
            body="# h1-name\n\ntext",
        )
        fm, _ = _parse_skill_md(content)
        assert fm["name"] == "fm-name"

    def test_nested_yaml_frontmatter(self):
        content = _make_skill_md(
            frontmatter=(
                "name: nested\ndescription: test\n"
                "metadata:\n  author: me\n  version: 2.0"
            ),
            body="\n# Nested Skill",
        )
        fm, body = _parse_skill_md(content)
        assert fm["name"] == "nested"
        assert isinstance(fm["metadata"], dict)
        assert fm["metadata"]["author"] == "me"

    def test_extra_yaml_fields_preserved(self):
        content = _make_skill_md(
            frontmatter="name: test\nlicense: MIT\ntags: [ai, coding]",
            body="\nbody",
        )
        fm, _ = _parse_skill_md(content)
        assert fm["license"] == "MIT"
        assert fm["tags"] == ["ai", "coding"]

    def test_no_body_after_frontmatter(self):
        content = "---\nname: no-body\n---\n"
        fm, body = _parse_skill_md(content)
        assert fm["name"] == "no-body"
        assert body.strip() == ""


# ─── Test summary extraction ────────────────────────────────────────────────────


class TestExtractSummary:
    def test_first_30_lines(self):
        lines = [f"Line {i}" for i in range(1, 50)]
        body = "\n".join(lines)
        summary = _extract_summary(body)
        assert len(summary.split("\n")) == 30

    def test_stops_at_blank_line(self):
        body = "line1\nline2\n\nline4\nline5"
        summary = _extract_summary(body)
        assert summary == "line1\nline2"

    def test_single_line(self):
        summary = _extract_summary("only one line")
        assert summary == "only one line"

    def test_empty_body(self):
        summary = _extract_summary("")
        assert summary == ""


# ─── Test hash computation ─────────────────────────────────────────────────────


class TestComputeHashes:
    def test_composite_hash_sorted_by_path(self):
        # Same content in different file order should produce same hash
        files_a = {"a.txt": "hello", "b.txt": "world"}
        files_b = {"b.txt": "world", "a.txt": "hello"}
        zip_a = _make_zip(files_a)
        zip_b = _make_zip(files_b)
        hash_a, _ = _compute_hashes(zip_a)
        hash_b, _ = _compute_hashes(zip_b)
        assert hash_a == hash_b
        assert hash_a != ""

    def test_composite_hash_deterministic(self):
        zip_bytes = _make_zip({"f.txt": "content"})
        h1, _ = _compute_hashes(zip_bytes)
        h2, _ = _compute_hashes(zip_bytes)
        assert h1 == h2

    def test_file_hashes_includes_all_files(self):
        zip_bytes = _make_zip({"x.md": "a", "y.md": "b", "z.md": "c"})
        _, fh = _compute_hashes(zip_bytes)
        assert set(fh.keys()) == {"x.md", "y.md", "z.md"}

    def test_empty_zip(self):
        h, fh = _compute_hashes(b"")
        assert h == ""
        assert fh == {}

    def test_invalid_zip(self):
        h, fh = _compute_hashes(b"not-a-zip")
        assert h == ""
        assert fh == {}

    def test_hashes_are_sha256(self):
        zip_bytes = _make_zip({"f.txt": "test"})
        _, fh = _compute_hashes(zip_bytes)
        expected = hashlib.sha256(b"test").hexdigest()
        assert fh["f.txt"]["sha256"] == expected
        assert fh["f.txt"]["size"] == 4


# ─── Test ZIP parsing ────────────────────────────────────────────────────────────


class TestParseSkillZip:
    def test_zip_with_root_skill_md(self):
        skill_md = "---\nname: root\n---\n\n# Root Skill\nContent."
        zip_bytes = _make_zip({"SKILL.md": skill_md})
        result = parse_skill_zip(zip_bytes)
        assert result.frontmatter["name"] == "root"
        assert "Content." in result.full_content
        assert result.summary_text != ""
        assert result.composite_hash != ""
        assert "SKILL.md" in result.file_hashes

    def test_zip_with_subdirectory_skill_md(self):
        skill_md = "---\nname: sub\n---\n\n# Sub Skill"
        zip_bytes = _make_zip({"src/SKILL.md": skill_md, "other.txt": "extra"})
        result = parse_skill_zip(zip_bytes)
        assert result.frontmatter["name"] == "sub"
        assert "other.txt" in result.file_hashes

    def test_zip_without_skill_md(self):
        zip_bytes = _make_zip({"README.md": "readme", "config.json": "{}"})
        result = parse_skill_zip(zip_bytes)
        assert result.frontmatter == {}
        assert result.summary_text == ""
        assert result.full_content == ""
        # Hashes still computed
        assert result.composite_hash != ""

    def test_empty_zip(self):
        result = parse_skill_zip(b"")
        assert result.frontmatter == {}
        assert result.composite_hash == ""

    def test_corrupt_zip(self):
        result = parse_skill_zip(b"not-a-zip")
        assert result.frontmatter == {}
        assert result.composite_hash == ""


# ─── Test apply_parsed_to_version ────────────────────────────────────────────


class TestApplyParsedToVersion:
    def test_writes_all_fields(self):
        parsed = ParsedSkillContent(
            frontmatter={"name": "test"},
            summary_text="summary",
            full_content="full",
            composite_hash="abc123",
            file_hashes={"f.txt": {"sha256": "hash1", "size": 5}},
        )
        version = type(
            "MockVersion",
            (),
            {
                "frontmatter": {},
                "summary_text": "",
                "full_content": "",
                "composite_hash": "",
                "file_hashes": {},
            },
        )()
        apply_parsed_to_version(version, parsed)
        assert version.frontmatter == {"name": "test"}
        assert version.summary_text == "summary"
        assert version.full_content == "full"
        assert version.composite_hash == "abc123"
        assert version.file_hashes == {"f.txt": {"sha256": "hash1", "size": 5}}
