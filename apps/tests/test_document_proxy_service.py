"""document_proxy_service 安全边界（SSRF / method 白名单）单测。

网络层转发（超时/截断/正常转发）依赖真实出站连接，留作 dev 手动验证（见 roadmap）。
"""

import pytest

from exceptions import ValidationError
from services.document_proxy_service import _validate_method, _validate_url


def test_validate_method_normalizes_to_upper():
    assert _validate_method("get") == "GET"
    assert _validate_method("Post") == "POST"
    assert _validate_method("DELETE") == "DELETE"


@pytest.mark.parametrize("bad", ["", "TRACE", "CONNECT", "HEAD", "OPTIONS", "get\n"])
def test_validate_method_rejects_disallowed(bad: str):
    with pytest.raises(ValidationError):
        _validate_method(bad)


def test_validate_url_rejects_non_http_scheme():
    with pytest.raises(ValidationError):
        _validate_url("ftp://example.com/x")
    with pytest.raises(ValidationError):
        _validate_url("file:///etc/passwd")


def test_validate_url_rejects_loopback():
    with pytest.raises(ValidationError):
        _validate_url("http://127.0.0.1/admin")
    with pytest.raises(ValidationError):
        _validate_url("http://[::1]/x")
    with pytest.raises(ValidationError):
        _validate_url("http://127.255.255.255/x")


def test_validate_url_rejects_cloud_metadata():
    with pytest.raises(ValidationError):
        _validate_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ValidationError):
        _validate_url("http://169.254.170.2/x")


def test_validate_url_rejects_missing_host():
    with pytest.raises(ValidationError):
        _validate_url("http:///path")
