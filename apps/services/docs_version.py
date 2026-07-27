"""文档库版本号校验。

docs-mcp 用 node-semver 的 semver.valid 校验版本号，仅接受 X.Y.Z 三段格式
（可选 v 前缀）。非标准格式（如 v1.0、1.0、2024Q1）入库后，搜索时
findBestVersion 会将其过滤为空并抛错，导致 /api/search 经 best-version
解析时 500。

入库前在此拦截：留空（unversioned，docs-mcp 原生支持）或完整三段版本号。
"""

import re

DOCS_VERSION_PATTERN = r"^v?\d+\.\d+\.\d+$"
DOCS_VERSION_RE = re.compile(DOCS_VERSION_PATTERN)
DOCS_VERSION_ERROR_MSG = "版本号格式无效，请留空或填写完整版本号（如 1.0.0）"


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
