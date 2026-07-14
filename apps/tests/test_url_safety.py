import pytest

from core.url_safety import assert_safe_url, contains_nginx_metacharacters, validate_url
from exceptions import ValidationError

# ─── 基础校验（原有） ──────────────────────────────────────────────────────


def test_url_safety_public_ip_accepted():
    assert_safe_url("http://8.8.8.8")
    assert_safe_url("https://1.1.1.1")


def test_url_safety_invalid_scheme_rejected():
    with pytest.raises(ValidationError):
        assert_safe_url("file:///etc/passwd")
    with pytest.raises(ValidationError):
        assert_safe_url("ftp://example.com")


def test_url_safety_missing_host_rejected():
    with pytest.raises(ValidationError):
        assert_safe_url("http://")


def test_url_safety_loopback_rejected():
    for url in ("http://127.0.0.1", "http://localhost", "http://[::1]"):
        with pytest.raises(ValidationError):
            assert_safe_url(url)


def test_url_safety_private_rejected():
    for url in ("http://10.1.2.3", "http://192.168.1.1", "http://172.16.0.1"):
        with pytest.raises(ValidationError):
            assert_safe_url(url)


def test_url_safety_link_local_rejected():
    with pytest.raises(ValidationError):
        assert_safe_url("http://169.254.169.254")


def test_url_safety_unspecified_rejected():
    with pytest.raises(ValidationError):
        assert_safe_url("http://0.0.0.0")


# ─── 增强校验（新增） ──────────────────────────────────────────────────────


def test_validate_url_returns_ips():
    """validate_url 应返回解析后的 IP 列表。"""
    ips = validate_url("http://8.8.8.8")
    assert isinstance(ips, list)
    assert len(ips) > 0
    assert "8.8.8.8" in ips


def test_validate_url_ipv4_mapped_ipv6_rejected():
    """IPv4-mapped IPv6 地址 ::ffff:10.0.0.1 应被识别为内网并拒绝。"""
    with pytest.raises(ValidationError):
        validate_url("http://[::ffff:10.0.0.1]")


def test_validate_url_ipv4_mapped_ipv6_rejected_short():
    with pytest.raises(ValidationError):
        validate_url("http://[::ffff:192.168.1.1]")


def test_validate_url_empty_rejected():
    with pytest.raises(ValidationError):
        validate_url("")
    with pytest.raises(ValidationError):
        validate_url("  ")


def test_validate_url_non_string_rejected():
    with pytest.raises(ValidationError):
        validate_url(None)


def test_validate_url_require_https_rejects_http():
    """require_https=True 时拒绝 http。"""
    with pytest.raises(ValidationError):
        validate_url("http://8.8.8.8", require_https=True)
    validate_url("https://8.8.8.8", require_https=True)


def test_validate_url_allowed_ports_rejects_non_standard():
    """allowed_ports 限制端口。"""
    with pytest.raises(ValidationError):
        validate_url("http://8.8.8.8:8080", allowed_ports={80, 443})


def test_validate_url_allowed_ports_accepts_standard():
    validate_url("http://8.8.8.8:80", allowed_ports={80, 443})
    validate_url("https://8.8.8.8:443", allowed_ports={80, 443})


def test_nginx_metacharacters_detected():
    assert contains_nginx_metacharacters("http://example.com/\r\nInjected: yes")
    assert contains_nginx_metacharacters("http://example.com/path\r\n")
    assert contains_nginx_metacharacters('http://example.com/{"x":"y"}')
    assert not contains_nginx_metacharacters("http://example.com/path")


def test_validate_url_reject_nginx_metacharacters():
    with pytest.raises(ValidationError):
        validate_url(
            "http://example.com/path\r\nInject", reject_nginx_metacharacters=True
        )
