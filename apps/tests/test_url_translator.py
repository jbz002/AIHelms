import pytest
from unittest.mock import patch, MagicMock

from core.url_translator import translate_repo_url
from exceptions import ValidationError


def _mock_settings(domains: str):
    s = MagicMock()
    s.ssrf_skill_url_domains = domains
    return s


def test_translate_github_url():
    with patch("core.config.settings", _mock_settings("github.com")):
        result = translate_repo_url("https://github.com/owner/repo/tree/main/skills/my-skill")
    assert result.platform == "github"
    assert result.owner == "owner"
    assert result.repo == "repo"
    assert result.ref == "main"
    assert "codeload.github.com" in result.download_url


def test_translate_github_url_no_ref_defaults_main():
    with patch("core.config.settings", _mock_settings("github.com")):
        result = translate_repo_url("https://github.com/owner/repo")
    assert result.ref == "main"


def test_translate_gitee_url():
    with patch("core.config.settings", _mock_settings("gitee.com")):
        result = translate_repo_url("https://gitee.com/owner/repo/tree/master")
    assert result.platform == "gitee"
    assert result.owner == "owner"
    assert result.repo == "repo"
    assert result.ref == "master"
    assert "gitee.com" in result.download_url
    assert "archive" in result.download_url


def test_translate_gitlab_url():
    with patch("core.config.settings", _mock_settings("gitlab.com")):
        result = translate_repo_url("https://gitlab.com/owner/repo/-/tree/main")
    assert result.platform == "gitlab"
    assert result.owner == "owner"
    assert result.repo == "repo"
    assert "archive" in result.download_url


def test_translate_non_whitelisted_domain_rejected():
    with patch("core.config.settings", _mock_settings("github.com,gitee.com")):
        with pytest.raises(ValidationError):
            translate_repo_url("https://bitbucket.org/owner/repo/tree/main")


def test_translate_empty_url_rejected():
    with pytest.raises(ValidationError):
        translate_repo_url("")
    with pytest.raises(ValidationError):
        translate_repo_url("not-a-url")


def test_translate_malformed_url_rejected():
    with patch("core.config.settings", _mock_settings("github.com")):
        with pytest.raises(ValidationError):
            translate_repo_url("https://github.com/")
        with pytest.raises(ValidationError):
            translate_repo_url("https://github.com/only-owner")


def test_translate_default_domains_when_config_empty():
    """配置为空时使用默认域名 github.com, gitee.com, gitlab.com。"""
    with patch("core.config.settings", _mock_settings("")):
        result = translate_repo_url("https://github.com/owner/repo/tree/main")
        assert result.platform == "github"
