"""Skill URL 翻译器：将仓库 URL 翻译为可下载的 zip URL。

仅支持白名单仓库域名（通过 ssrf_skill_url_domains 配置）。
支持 GitHub、Gitee、GitLab（含自建实例）。
"""

import re
from dataclasses import dataclass

from exceptions import ValidationError

# GitHub: /owner/repo/tree/ref/path 或 /owner/repo/blob/ref/path
_GITHUB_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)"
    r"(?:/(?:tree|blob)/(?P<ref>[^/]+)(?:/(?P<path>.+))?)?$"
)

# Gitee: /owner/repo/tree/ref/path
_GITEE_RE = re.compile(
    r"^https?://gitee\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)"
    r"(?:/(?:tree|blob)/(?P<ref>[^/]+)(?:/(?P<path>.+))?)?$"
)

# GitLab: /owner/repo/-/tree/ref/path
_GITLAB_RE = re.compile(
    r"^https?://(?P<domain>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+)"
    r"(?:/-/(?:tree|blob)/(?P<ref>[^/]+)(?:/(?P<path>.+))?)?$"
)


@dataclass(frozen=True)
class TranslatedUrl:
    download_url: str
    owner: str
    repo: str
    ref: str
    platform: str
    source_url: str


def _get_allowed_domains() -> set[str]:
    from core.config import settings

    domains: set[str] = set()
    for d in (settings.ssrf_skill_url_domains or "").split(","):
        d = d.strip().lower()
        if d:
            domains.add(d)
    if not domains:
        domains = {"github.com", "gitee.com", "gitlab.com"}
    return domains


def _translate_github(m: re.Match, source_url: str) -> TranslatedUrl:
    owner, repo, ref, _path = m.group("owner"), m.group("repo"), m.group("ref"), m.group("path")
    if not ref:
        ref = "main"
    download_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{ref}"
    return TranslatedUrl(
        download_url=download_url,
        owner=owner,
        repo=repo,
        ref=ref,
        platform="github",
        source_url=source_url,
    )


def _translate_gitee(m: re.Match, source_url: str) -> TranslatedUrl:
    owner, repo, ref = m.group("owner"), m.group("repo"), m.group("ref")
    if not ref:
        ref = "master"
    download_url = f"https://gitee.com/{owner}/{repo}/repository/archive/{ref}.zip"
    return TranslatedUrl(
        download_url=download_url,
        owner=owner,
        repo=repo,
        ref=ref,
        platform="gitee",
        source_url=source_url,
    )


def _translate_gitlab(m: re.Match, source_url: str) -> TranslatedUrl:
    domain, owner, repo, ref = (
        m.group("domain"), m.group("owner"), m.group("repo"), m.group("ref"),
    )
    if not ref:
        ref = "main"
    safe_ref = ref.replace("/", "-")
    download_url = f"https://{domain}/{owner}/{repo}/-/archive/{ref}/{repo}-{safe_ref}.zip"
    return TranslatedUrl(
        download_url=download_url,
        owner=owner,
        repo=repo,
        ref=ref,
        platform="gitlab",
        source_url=source_url,
    )


def translate_repo_url(url: str) -> TranslatedUrl:
    """将仓库 URL 翻译为 zip 下载 URL。

    仅允许白名单仓库域名，不匹配则抛 ValidationError。
    """
    if not url or not isinstance(url, str):
        raise ValidationError("仓库 URL 为空或格式不正确")

    parsed_domain = url.split("/")[2] if "//" in url else url.split("/")[0]
    parsed_domain = parsed_domain.lower().split(":")[0]

    allowed = _get_allowed_domains()
    if parsed_domain not in allowed:
        raise ValidationError(f"该仓库域名不在允许列表中: {parsed_domain}")

    if parsed_domain == "github.com":
        m = _GITHUB_RE.match(url)
        if m:
            return _translate_github(m, url)

    if parsed_domain == "gitee.com":
        m = _GITEE_RE.match(url)
        if m:
            return _translate_gitee(m, url)

    # GitLab（含自建）
    m = _GITLAB_RE.match(url)
    if m and parsed_domain != "github.com" and parsed_domain != "gitee.com":
        return _translate_gitlab(m, url)

    raise ValidationError(f"无法识别的仓库 URL 格式: {url}")
