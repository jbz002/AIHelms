"""URL 安全校验：防止 SSRF，拒绝内网/环回/链路本地等非公网目标。"""

import ipaddress
import socket
from urllib.parse import urlparse

from exceptions import ValidationError

_ALLOWED_SCHEMES = {"http", "https"}


def assert_safe_url(url: str) -> None:
    """校验 URL，不通过则抛 ValidationError。

    检查项：scheme 仅允许 http/https；主机名必须存在；解析主机名后拒绝任何
    私有/环回/链路本地/保留/多播/未指定地址。

    已知限制：仅在解析期校验，不防 DNS rebinding（攻击者可能在解析后、连接前
    切换 IP）。完整防护需在 socket 连接层拦截，当前 MVP 未实现。
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValidationError(f"不支持的 URL 协议: {parsed.scheme or '空'}")

    host = parsed.hostname
    if not host:
        raise ValidationError("URL 缺少主机名")

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValidationError(f"无法解析主机名: {host}") from e

    for addr_info in addr_infos:
        ip = ipaddress.ip_address(addr_info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValidationError(f"禁止访问非公网地址: {ip}")
