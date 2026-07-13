import pytest

from core.url_safety import assert_safe_url
from exceptions import ValidationError


def test_url_safety_public_ip_accepted():
    # IP 字面量不经 DNS，测试稳定不依赖网络
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
        assert_safe_url("http://169.254.169.254")  # 云元数据端点


def test_url_safety_unspecified_rejected():
    with pytest.raises(ValidationError):
        assert_safe_url("http://0.0.0.0")
