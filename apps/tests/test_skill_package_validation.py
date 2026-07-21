"""Tests for skill_package_validator — Skill ZIP 包物理安全校验（模块 S5）。

纯函数测试，无需 DB。覆盖 zip slip / 扩展名白名单 / magic bytes / 大小限制 /
文件数上限 / zip bomb（压缩与解压双校验）/ 白名单覆盖语义。
恶意 zip 在 BytesIO 内运行时构造（ZipInfo 不清洗 .. 片段）。
"""

from __future__ import annotations

import io
import random
import zipfile

import pytest

from exceptions import ValidationError
from services.skill_package_validator import (
    DEFAULT_ALLOWED_EXTENSIONS,
    PackageValidationResult,
    _is_unsafe_path,
    safe_extract_path,
    validate_skill_package,
)
from services.skill_service import _validate_package_or_raise


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _zip_symlink(name: str, target: str) -> bytes:
    info = zipfile.ZipInfo(name)
    info.external_attr = 0o120777 << 16  # S_IFLNK
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(info, target)
    return buf.getvalue()


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _codes(result: PackageValidationResult) -> list[str]:
    return [e.code for e in result.errors]


# ─── 合规通过 ─────────────────────────────────────────────────────────────────


def test_valid_package_passes():
    zip_bytes = _zip(
        {
            "SKILL.md": b"---\nname: demo\ndescription: x\n---\nbody",
            "scripts/run.sh": b"#!/bin/sh\necho hi",
            "assets/logo.png": _png_bytes(),
        }
    )
    result = validate_skill_package(zip_bytes)
    assert result.valid is True
    assert result.errors == []
    assert result.checked_files == 3


def test_empty_whitelist_uses_default_py_allowed():
    # 默认白名单包含 .py
    zip_bytes = _zip({"src/main.py": b"print('hi')"})
    result = validate_skill_package(zip_bytes)
    assert result.valid is True


# ─── zip slip ──────────────────────────────────────────────────────────────────


def test_zip_slip_dotdot_rejected():
    zip_bytes = _zip({"../escape.md": b"x", "legit.md": b"y"})
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "path.zip_slip" in _codes(result)
    assert any(i.file_path == "../escape.md" for i in result.errors)


def test_zip_slip_absolute_path_rejected():
    zip_bytes = _zip({"/etc/passwd": b"x"})
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "path.zip_slip" in _codes(result)


def test_zip_slip_backslash_rejected():
    # Windows 形式穿越，跨平台均须拒绝
    zip_bytes = _zip({"..\\..\\win-escape.md": b"x"})
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "path.zip_slip" in _codes(result)


def test_zip_slip_drive_letter_rejected():
    zip_bytes = _zip({"C:/evil.md": b"x"})
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "path.zip_slip" in _codes(result)


def test_zip_slip_symlink_member_rejected():
    zip_bytes = _zip_symlink("link.txt", "/etc/passwd")
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "path.zip_slip" in _codes(result)


def test_is_unsafe_path_unit():
    assert _is_unsafe_path("../x") is True
    assert _is_unsafe_path("/abs") is True
    assert _is_unsafe_path("C:/x") is True
    assert _is_unsafe_path("") is True
    assert _is_unsafe_path("a/../b") is True
    assert _is_unsafe_path("scripts/run.sh") is False
    assert _is_unsafe_path("a/b/c.md") is False


# ─── 扩展名白名单 ─────────────────────────────────────────────────────────────


def test_non_whitelist_extension_rejected():
    zip_bytes = _zip({"evil.exe": b"MZ"})
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "ext.not_allowed" in _codes(result)
    assert any(i.file_path == "evil.exe" for i in result.errors)


def test_whitelist_override_replaces_default(monkeypatch):
    # 整体替换：只允许 .md/.json，.py 被拒
    monkeypatch.setattr(
        "services.skill_package_validator.settings.skills_package_allowed_extensions",
        ".md,.json",
    )
    zip_bytes = _zip({"src/main.py": b"print('hi')"})
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "ext.not_allowed" in _codes(result)


def test_default_whitelist_contents():
    # .exe/.dll 永不在默认白名单
    assert ".py" in DEFAULT_ALLOWED_EXTENSIONS
    assert ".sh" in DEFAULT_ALLOWED_EXTENSIONS
    assert ".exe" not in DEFAULT_ALLOWED_EXTENSIONS
    assert ".dll" not in DEFAULT_ALLOWED_EXTENSIONS


# ─── magic bytes ──────────────────────────────────────────────────────────────


def test_magic_mismatch_rejected():
    # .png 实为 PE 头
    zip_bytes = _zip({"evil.png": b"MZ\x90\x00" + b"\x00" * 200})
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "magic.mismatch" in _codes(result)
    assert any(i.file_path == "evil.png" for i in result.errors)


def test_magic_valid_png_passes():
    zip_bytes = _zip({"ok.png": _png_bytes()})
    result = validate_skill_package(zip_bytes)
    assert result.valid is True


# ─── 大小 / 文件数 / zip bomb ──────────────────────────────────────────────────


def test_oversized_single_file_rejected(monkeypatch):
    monkeypatch.setattr(
        "services.skill_package_validator.settings.skills_package_max_file_size_mb",
        0,
    )
    zip_bytes = _zip({"big.md": b"x"})
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "size.single_file" in _codes(result)


def test_too_many_files_rejected(monkeypatch):
    monkeypatch.setattr(
        "services.skill_package_validator.settings.skills_package_max_file_count",
        5,
    )
    zip_bytes = _zip({f"f{i}.md": b"x" for i in range(6)})
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "count.too_many" in _codes(result)


def test_total_uncompressed_oversize_rejected(monkeypatch):
    # 解压总体积超限（压缩后很小，靠双校验防 zip bomb）
    monkeypatch.setattr(
        "services.skill_package_validator.settings.skills_package_max_total_size_mb",
        1,
    )
    content = b"a" * 600_000  # 高度可压缩，压缩后远小于 1MB
    zip_bytes = _zip({f"f{i}.md": content for i in range(2)})  # 解压后 1.2MB
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "size.package_uncompressed" in _codes(result)
    assert "size.package_compressed" not in _codes(result)


def test_compressed_oversize_short_circuits(monkeypatch):
    # 压缩体积超限 → 直接返回，不解析成员
    monkeypatch.setattr(
        "services.skill_package_validator.settings.skills_package_max_total_size_mb",
        1,
    )
    random.seed(0)
    payload = random.randbytes(1_200_000)  # 不可压缩 → 压缩后仍 > 1MB
    zip_bytes = _zip({"bomb.bin": payload})
    result = validate_skill_package(zip_bytes)
    assert result.valid is False
    assert "size.package_compressed" in _codes(result)
    assert result.checked_files == 0


# ─── 损坏 zip ──────────────────────────────────────────────────────────────────


def test_corrupt_zip_rejected():
    result = validate_skill_package(b"PK\x03\x04 not a real zip")
    assert result.valid is False
    assert "zip.bad" in _codes(result)


# ─── service 包装层 ───────────────────────────────────────────────────────────


def test_service_wrapper_raises_validation_error():
    zip_bytes = _zip({"../escape.md": b"x"})
    with pytest.raises(ValidationError) as exc_info:
        _validate_package_or_raise(zip_bytes, "test")
    msg = str(exc_info.value)
    assert "Skill 包物理校验未通过" in msg
    assert "../escape.md" in msg


def test_service_wrapper_valid_package_passes():
    zip_bytes = _zip({"SKILL.md": b"---\nname: demo\ndescription: x\n---\nbody"})
    # 不抛异常即通过
    _validate_package_or_raise(zip_bytes, "test")


def test_service_wrapper_caps_errors_at_20():
    # 25 个非白名单文件 → 消息含前 20 条 + 溢出计数
    zip_bytes = _zip({f"f{i}.exe": b"MZ" for i in range(25)})
    with pytest.raises(ValidationError) as exc_info:
        _validate_package_or_raise(zip_bytes, "test")
    msg = str(exc_info.value)
    assert "另有 5 条问题" in msg
    # 计数文件出现次数 = 20（上限）
    assert msg.count("f") >= 20


# ─── safe_extract_path 工具 ────────────────────────────────────────────────────


def test_safe_extract_path_unit(tmp_path):
    base = tmp_path
    assert safe_extract_path(base, "a/b.md") == (base / "a" / "b.md").resolve()
    assert safe_extract_path(base, "../escape.md") is None
    assert safe_extract_path(base, "/etc/passwd") is None
