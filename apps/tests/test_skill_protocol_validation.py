"""Tests for skill_protocol_service — SKILL.md 协议合规校验（模块 S1）。

纯函数测试，无需 DB。校验逻辑消费 skill_content_service 的解析结果。
"""

import hashlib
import io
import zipfile

from services.skill_content_service import _compute_hashes, parse_skill_zip
from services.skill_protocol_service import validate_skill_protocol


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _skill_md(name: str = "my-skill", description: str = "A test skill.") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# My Skill\n\nBody."


def _error_codes(result) -> list[str]:
    return [e.code for e in result.errors]


def _warning_codes(result) -> list[str]:
    return [w.code for w in result.warnings]


# ─── 合规通过 ────────────────────────────────────────────────────────────────


def test_valid_kebab_name_passes():
    zip_bytes = _make_zip({"SKILL.md": _skill_md()})
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    assert result.valid is True
    assert result.errors == []
    entry = result.manifest["SKILL.md"]
    assert entry["category"] == "root"
    assert "sha256" in entry and entry["sha256"] != ""
    assert entry["size"] > 0
    assert entry["content_type"]


def test_manifest_categories_for_standard_dirs():
    zip_bytes = _make_zip(
        {
            "SKILL.md": _skill_md(),
            "references/guide.md": "# Guide",
            "scripts/run.sh": "#!/bin/sh",
            "assets/logo.png": "fake-png",
        }
    )
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    assert result.valid is True
    assert result.manifest["references/guide.md"]["category"] == "references"
    assert result.manifest["scripts/run.sh"]["category"] == "scripts"
    assert result.manifest["assets/logo.png"]["category"] == "assets"


# ─── errors ──────────────────────────────────────────────────────────────────


def test_missing_skill_md_returns_error():
    zip_bytes = _make_zip({"README.md": "# readme"})
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    assert result.valid is False
    assert "skill_md.missing" in _error_codes(result)


def test_name_not_kebab_returns_error():
    zip_bytes = _make_zip({"SKILL.md": _skill_md(name="MySkill")})
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    assert result.valid is False
    assert "name.not_kebab" in _error_codes(result)


def test_name_uppercase_rejected():
    zip_bytes = _make_zip({"SKILL.md": _skill_md(name="my_skill")})
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    assert "name.not_kebab" in _error_codes(result)


def test_name_double_hyphen_rejected():
    zip_bytes = _make_zip({"SKILL.md": _skill_md(name="my--skill")})
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    assert result.valid is False
    assert "name.double_hyphen" in _error_codes(result)


def test_missing_description_returns_error():
    # 空 body：解析器无法从首段回填 description，触发缺失错误
    zip_bytes = _make_zip({"SKILL.md": "---\nname: my-skill\n---\n"})
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    assert result.valid is False
    assert "description.missing" in _error_codes(result)


# ─── warnings ────────────────────────────────────────────────────────────────


def test_non_standard_dir_returns_warning():
    zip_bytes = _make_zip({"SKILL.md": _skill_md(), "docs/extra.md": "# extra"})
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    assert result.valid is True
    assert "dir.non_standard" in _warning_codes(result)


def test_wrapped_top_dir_not_flagged_non_standard():
    """Anthropic 官方布局：整个 skill 包在同名外层目录里（pdf/SKILL.md ...）。
    外层目录是 skill 根，不应被当成非标准子目录；其下的 scripts/ 应正确分类。
    """
    zip_bytes = _make_zip(
        {
            "pdf/SKILL.md": _skill_md(name="pdf"),
            "pdf/scripts/pdf_to_text.py": "# script",
            "pdf/references/format.md": "# ref",
            "pdf/assets/icon.svg": "<svg/>",
        }
    )
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    assert result.valid is True
    assert "dir.non_standard" not in _warning_codes(result)
    assert "name.dir_mismatch" not in _warning_codes(result)
    assert result.manifest["pdf/SKILL.md"]["category"] == "root"
    assert result.manifest["pdf/scripts/pdf_to_text.py"]["category"] == "scripts"
    assert result.manifest["pdf/references/format.md"]["category"] == "references"
    assert result.manifest["pdf/assets/icon.svg"]["category"] == "assets"


def test_wrapped_non_standard_subdir_flagged():
    """外层根目录剥离后，真正的非标准子目录仍应告警。"""
    zip_bytes = _make_zip(
        {
            "pdf/SKILL.md": _skill_md(name="pdf"),
            "pdf/randomdir/note.md": "# note",
        }
    )
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    assert "dir.non_standard" in _warning_codes(result)
    assert (
        result.warnings[0].message
        == "非标准目录 'randomdir/'，建议使用 references/ scripts/ assets/"
    )


def test_description_too_long_returns_warning():
    long_desc = "x" * 300
    zip_bytes = _make_zip({"SKILL.md": _skill_md(description=long_desc)})
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    assert result.valid is True
    assert "description.too_long" in _warning_codes(result)


def test_to_storage_list_merges_errors_and_warnings():
    zip_bytes = _make_zip(
        {
            "SKILL.md": _skill_md(name="MySkill", description="x" * 300),
        }
    )
    result = validate_skill_protocol(parse_skill_zip(zip_bytes))
    storage = result.to_storage_list()
    severities = {item["severity"] for item in storage}
    assert "error" in severities
    assert "warning" in severities
    assert all({"severity", "code", "message"} <= set(item) for item in storage)


# ─── composite_hash 稳定性 ──────────────────────────────────────────────────


def test_composite_hash_stable_after_manifest_upgrade():
    """升级 file_hashes value 结构后，composite_hash 公式应保持不变：
    sha256("".join(f"{path}:{sha}"))，不触发 S9 误报漂移。"""
    zip_bytes = _make_zip({"SKILL.md": _skill_md(), "references/a.md": "# A"})
    composite, file_hashes = _compute_hashes(zip_bytes)
    manual = hashlib.sha256(
        "".join(
            f"{path}:{entry['sha256']}" for path, entry in sorted(file_hashes.items())
        ).encode()
    ).hexdigest()
    assert composite == manual
    # 值结构已升级为 dict
    assert isinstance(file_hashes["SKILL.md"], dict)
    assert {"sha256", "size"} <= set(file_hashes["SKILL.md"])
