r"""Skill ZIP 包物理安全校验（模块 S5）。

在 ``skill_service.create_skill`` / ``create_version`` 写盘前对 zip 字节流做
fail-closed 物理安全门控：zip slip 路径穿越、扩展名白名单、magic bytes、
单文件 / 总包 / 文件数上限。

参考 skillhub（``D:\project\demo\skillhub``）：
- ``SkillPackagePolicy.java``：大小 / 白名单 / magic bytes / 路径归一化
- ``SkillPublishService.java:349-388``：验证链编排

本模块只做物理安全；SKILL.md 协议语义校验属 S1 范围。校验失败由
``skill_service._validate_package_or_raise`` 抛 ``ValidationError``，
全局 handler 转 400。

zip bomb 防御：同时校验压缩体积（``len(zip_bytes)``）与解压体积
（``sum(info.file_size)``）；magic 检查只读前若干字节，绝不全量解压。
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from core.config import settings

logger = logging.getLogger(__name__)

# 单成员 magic bytes 读取上限（足够覆盖 PNG/JPG/GIF/PDF/WEBP/ICO 文件头）
_MAGIC_READ_BYTES = 16

# Unix 文件类型掩码与符号链接位（zipinfo.external_attr 高 16 位存 Unix mode）
_S_IFMT = 0o170000
_S_IFLNK = 0o120000

# 默认扩展名白名单：留空配置时使用。管理员可用 SKILLS_PACKAGE_ALLOWED_EXTENSIONS 整体替换
DEFAULT_ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # 文档
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".csv",
        ".toml",
        ".xml",
        ".ini",
        ".cfg",
        ".html",
        ".css",
        # 脚本源码
        ".js",
        ".ts",
        ".py",
        ".sh",
        ".rb",
        ".go",
        ".rs",
        # 图片 / 文档
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".svg",
        ".pdf",
    }
)

# 扩展名 → 期望文件头前缀（文本类不在此表，按 UTF-8 容忍）
_MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".pdf": (b"%PDF-",),
    ".ico": (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"),
}


@dataclass
class PackageIssue:
    """单条校验问题。"""

    severity: str  # "error" | "warning"
    code: str  # path.zip_slip / ext.not_allowed / magic.mismatch / size.* / count.too_many / zip.*
    message: str  # 中文，面向用户
    file_path: str = ""  # 包内成员路径，包级问题留空

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "file_path": self.file_path,
        }


@dataclass
class PackageValidationResult:
    """包校验结果。valid 仅由 errors 决定（warnings 不阻断）。"""

    errors: list[PackageIssue] = field(default_factory=list)
    warnings: list[PackageIssue] = field(default_factory=list)
    checked_files: int = 0
    uncompressed_bytes: int = 0

    @property
    def valid(self) -> bool:
        return not self.errors


def _resolve_allowed_extensions() -> frozenset[str]:
    """解析生效的扩展名白名单：配置空 → 默认；非空 → 整体替换。"""
    raw = settings.skills_package_allowed_extensions.strip()
    if not raw:
        return DEFAULT_ALLOWED_EXTENSIONS
    parts = {
        "." + part.strip().lower().lstrip(".")
        for part in raw.split(",")
        if part.strip()
    }
    return parts or DEFAULT_ALLOWED_EXTENSIONS


def _is_symlink_member(info: zipfile.ZipInfo) -> bool:
    """识别符号链接 entry（external_attr 高 16 位 Unix mode 的 S_IFLNK）。"""
    return (info.external_attr >> 16) & _S_IFMT == _S_IFLNK


def _is_unsafe_path(member_path: str) -> bool:
    """zip slip 检测：绝对路径 / 穿越片段 / 反斜杠穿越 / 盘符 / 空名。"""
    normalized = member_path.replace("\\", "/")
    if not normalized or normalized == "/":
        return True
    if normalized.startswith("/"):
        return True
    # Windows 盘符（如 C:/...）
    if len(normalized) >= 2 and normalized[1] == ":":
        return True
    return ".." in PurePosixPath(normalized).parts


def _path_issue(name: str) -> PackageIssue:
    return PackageIssue(
        severity="error",
        code="path.zip_slip",
        message="路径包含穿越片段（../、绝对路径、反斜杠或盘符），整包拒绝",
        file_path=name,
    )


def _read_head(zf: zipfile.ZipFile, name: str) -> bytes | None:
    """读取成员前 _MAGIC_READ_BYTES 字节；失败返回 None（不抛异常）。"""
    try:
        with zf.open(name, "r") as handle:
            return handle.read(_MAGIC_READ_BYTES)
    except (zipfile.BadZipFile, OSError, RuntimeError, KeyError):
        return None


def _check_magic(zf: zipfile.ZipFile, name: str, ext: str) -> PackageIssue | None:
    """按扩展名校验文件头；文本类（不在 _MAGIC_PREFIXES）跳过。"""
    if ext == ".webp":
        head = _read_head(zf, name)
        if head is None:
            return PackageIssue("error", "zip.read_failed", "无法读取文件内容", name)
        if not head.startswith(b"RIFF") or head[8:12] != b"WEBP":
            return PackageIssue(
                "error",
                "magic.mismatch",
                "WEBP 文件头不匹配（期望 RIFF....WEBP）",
                name,
            )
        return None
    if ext == ".svg":
        head = _read_head(zf, name)
        if head is None:
            return PackageIssue("error", "zip.read_failed", "无法读取文件内容", name)
        text = head.lstrip()[:5].lower()
        if text.startswith(b"<?xml") or text.startswith(b"<svg"):
            return None
        return PackageIssue(
            "error", "magic.mismatch", "SVG 内容未以 <?xml 或 <svg 开头", name
        )
    expected = _MAGIC_PREFIXES.get(ext)
    if not expected:
        return None  # 文本类：UTF-8 容忍，不校验 magic
    head = _read_head(zf, name)
    if head is None:
        return PackageIssue("error", "zip.read_failed", "无法读取文件内容", name)
    if not any(head.startswith(prefix) for prefix in expected):
        return PackageIssue(
            "error", "magic.mismatch", f"文件头与扩展名 '{ext}' 不符，疑似伪装", name
        )
    return None


def _mb(num_bytes: int) -> int:
    return num_bytes // 1024 // 1024


def validate_skill_package(zip_bytes: bytes) -> PackageValidationResult:
    """对 zip 字节流做物理安全校验，返回问题清单（不抛异常）。"""
    errors: list[PackageIssue] = []
    warnings: list[PackageIssue] = []
    allowed = _resolve_allowed_extensions()
    max_single = settings.skills_package_max_file_size_mb * 1024 * 1024
    max_total = settings.skills_package_max_total_size_mb * 1024 * 1024
    max_count = settings.skills_package_max_file_count

    # 1. 压缩体积预扫（fail-fast，避免解析巨型包）
    if len(zip_bytes) > max_total:
        errors.append(
            PackageIssue(
                "error",
                "size.package_compressed",
                f"压缩包体积 {_mb(len(zip_bytes))} MB 超过上限 "
                f"{settings.skills_package_max_total_size_mb} MB",
            )
        )
        return PackageValidationResult(errors=errors, warnings=warnings)

    # 2. zip 完整性
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        errors.append(PackageIssue("error", "zip.bad", "不是合法的 ZIP 文件"))
        return PackageValidationResult(errors=errors, warnings=warnings)

    total_uncompressed = 0
    checked = 0
    with zf:
        infos = zf.infolist()
        # 3. 文件数上限（继续收集其他问题以便一次性反馈）
        if len(infos) > max_count:
            errors.append(
                PackageIssue(
                    "error",
                    "count.too_many",
                    f"包内条目数 {len(infos)} 超过上限 {max_count}",
                )
            )
        # 4. 逐成员
        for info in infos:
            name = info.filename
            is_dir = name.endswith("/")
            if _is_symlink_member(info) or _is_unsafe_path(name):
                errors.append(_path_issue(name))
                continue
            if is_dir:
                continue
            checked += 1
            ext = PurePosixPath(name.lower()).suffix
            if ext not in allowed:
                errors.append(
                    PackageIssue(
                        "error",
                        "ext.not_allowed",
                        f"扩展名 '{ext}' 不在白名单",
                        name,
                    )
                )
                continue
            if info.file_size > max_single:
                errors.append(
                    PackageIssue(
                        "error",
                        "size.single_file",
                        f"文件体积 {_mb(info.file_size)} MB 超过单文件上限 "
                        f"{settings.skills_package_max_file_size_mb} MB",
                        name,
                    )
                )
            total_uncompressed += info.file_size
            magic_err = _check_magic(zf, name, ext)
            if magic_err:
                errors.append(magic_err)

    # 5. 解压总体积上限（zip bomb 防御）
    if total_uncompressed > max_total:
        errors.append(
            PackageIssue(
                "error",
                "size.package_uncompressed",
                f"解压后总体积 {_mb(total_uncompressed)} MB 超过上限 "
                f"{settings.skills_package_max_total_size_mb} MB",
            )
        )

    return PackageValidationResult(
        errors=errors,
        warnings=warnings,
        checked_files=checked,
        uncompressed_bytes=total_uncompressed,
    )


def safe_extract_path(target_dir: Path, member_path: str) -> Path | None:
    """返回 target_dir 内的安全解压路径，越界或路径穿越返回 None。

    预留工具：当前 app 不在 Python 中解压到磁盘（仅写 zip 原始 blob，
    Skillspector 与客户端后续解压）。S5 在注册期保证存量包路径安全；
    若未来新增解压点，应统一过此函数。
    """
    if _is_unsafe_path(member_path):
        return None
    base = Path(target_dir).resolve()
    target = (base / member_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target
