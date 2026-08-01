"""文档库版本号校验。

docs-mcp 用 node-semver 的 semver.valid 校验版本号，仅接受 X.Y.Z 三段格式
（可选 v 前缀）。非标准格式（如 v1.0、1.0、2024Q1）入库后，搜索时
findBestVersion 会将其过滤为空并抛错，导致 /api/search 经 best-version
解析时 500。

入库前在此拦截：留空（unversioned，docs-mcp 原生支持）或完整三段版本号。
"""

import re

from exceptions import ValidationError

DOCS_VERSION_PATTERN = r"^v?\d+\.\d+\.\d+$"
DOCS_VERSION_RE = re.compile(DOCS_VERSION_PATTERN)
DOCS_VERSION_ERROR_MSG = "版本号格式无效，请填写完整版本号（如 1.0.0）"


def normalize_docs_version(version: str | None) -> str | None:
    """规整版本号：去空白；空串/None → None（unversioned）。"""
    if version is None:
        return None
    trimmed = version.strip()
    return trimmed or None


def is_valid_docs_version(version: str | None) -> bool:
    """None（unversioned）合法；"latest" 哨兵合法（写入时由 service 解析）；其余须匹配 X.Y.Z。"""
    if version is None:
        return True
    if version.lower() == "latest":
        return True
    return bool(DOCS_VERSION_RE.match(version))


def require_docs_version(version: str | None) -> str:
    """写入边界强校验：必须是具体 X.Y.Z，禁止「无版本」桶。

    调用方应先用 docs_mcp_client.resolve_version(library, version) 把 "latest"
    解析为当时最新具体版本号，再过本函数——故到达此处的合法值只剩具体 X.Y.Z。
    None/''（留空或库空时 latest 解析失败）→ 拒；非 X.Y.Z → 拒。
    """
    if version is None or version.strip() == "":
        raise ValidationError("版本号不能为空，请填写完整版本号（如 1.0.0）")
    if not DOCS_VERSION_RE.match(version):
        raise ValidationError(DOCS_VERSION_ERROR_MSG)
    return version
