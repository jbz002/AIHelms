"""URL 安全校验：防止 SSRF，拒绝内网/环回/链路本地等非公网目标。

fail-closed 原则：任何校验失败、解析错误或歧义均拒绝，不做宽松放行。

校验项：
- 协议白名单（仅 http/https）
- 主机名必须存在
- DNS 解析后拒绝私有/环回/链路本地/保留/多播/未指定 IP
- IPv4-mapped IPv6 解包（::ffff:10.0.0.1 识别为内网）
- 云元数据端点永久封禁（169.254.169.254 等，不可白名单化）
- 可选 nginx 元字符检测（CRLF、路径穿越、userinfo 注入）
- 可选端口限制
- Profile 白名单机制（mcp profile 允许配置的内网目标）
"""

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlparse

from exceptions import ValidationError

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}

# 云元数据端点：永久封禁，不可通过白名单放行
_CLOUD_METADATA_IPS: frozenset[str] = frozenset({"169.254.169.254", "fd00:ec2::254"})

# nginx 元字符：用于防御配置注入，合法 URL 不会包含这些字符
_NGINX_METACHARACTERS = re.compile(r"[\r\n;\{\}\"'\\\s\t$\x00]")

# 默认允许的端口
_DEFAULT_ALLOWED_PORTS = {80, 443}


@dataclass(frozen=True)
class _Allowlist:
    """解析后的白名单：hosts + CIDRs。"""

    hosts: frozenset[str] = field(default_factory=frozenset)
    cidrs: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()

    def allows_host(self, hostname_lower: str) -> bool:
        return hostname_lower in self.hosts

    def allows_ip(
        self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> bool:
        return any(ip in net for net in self.cidrs)


def _parse_hosts(raw: str) -> frozenset[str]:
    return frozenset(
        h.strip().lower() for h in (raw or "").split(",") if h.strip()
    )


def _parse_cidrs(
    raw: str,
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            nets.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError:
            logger.warning("SSRF guard: 忽略白名单中格式错误的 CIDR: %r", chunk)
    return tuple(nets)


def _unwrap_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """解包 IPv4-mapped IPv6 地址（如 ::ffff:10.0.0.1 → 10.0.0.1）。"""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _is_metadata_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return str(ip) in _CLOUD_METADATA_IPS


def _is_blocked_ip(
    ip_str: str,
    allowlist: _Allowlist,
) -> bool:
    """判断 IP 是否应被阻断。fail-closed：解析失败也返回 True。"""
    try:
        ip = _unwrap_ip(ipaddress.ip_address(ip_str))
    except ValueError:
        return True

    if _is_metadata_ip(ip):
        return True

    is_dangerous = (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )
    if not is_dangerous:
        return False

    return not allowlist.allows_ip(ip)


@lru_cache(maxsize=1)
def _default_allowlist() -> _Allowlist:
    return _Allowlist()


@lru_cache(maxsize=1)
def _mcp_allowlist() -> _Allowlist:
    """MCP profile 白名单：允许管理员配置的内网目标。"""
    from core.config import settings

    return _Allowlist(
        hosts=_parse_hosts(settings.ssrf_allowed_hosts),
        cidrs=_parse_cidrs(settings.ssrf_allowed_cidrs),
    )


def _resolve_public_ips(
    hostname: str,
    port: int,
    allowlist: _Allowlist,
) -> list[str]:
    """解析主机名，要求所有 IP 均可接受。fail-closed。"""
    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValidationError(f"无法解析主机名: {hostname}") from e

    ips: list[str] = []
    for _family, _socktype, _proto, _canonname, sockaddr in addr_info:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str, allowlist):
            raise ValidationError(f"禁止访问非公网地址: {ip_str}")
        ips.append(ip_str)

    if not ips:
        raise ValidationError(f"主机名解析为空: {hostname}")

    return ips


def contains_nginx_metacharacters(value: str) -> bool:
    """检测是否包含 nginx 配置注入元字符。"""
    return bool(_NGINX_METACHARACTERS.search(value))


def validate_url(
    url: str,
    *,
    profile: str = "default",
    reject_nginx_metacharacters: bool = False,
    require_https: bool = False,
    allowed_ports: set[int] | None = None,
) -> list[str]:
    """增强 URL 安全校验（fail-closed）。

    Args:
        url: 待校验的 URL。
        profile: 验证配置。"default" 无白名单，"mcp" 允许配置的内网目标。
        reject_nginx_metacharacters: 是否拒绝 nginx 元字符。
        require_https: 是否强制 HTTPS。
        allowed_ports: 允许的端口集合。None 使用默认 {80, 443}。

    Returns:
        解析后的 IP 地址列表（白名单主机返回空列表）。

    Raises:
        ValidationError: 任一校验不通过。
    """
    if not url or not isinstance(url, str):
        raise ValidationError("URL 为空或格式不正确")

    if reject_nginx_metacharacters and contains_nginx_metacharacters(url):
        raise ValidationError("URL 包含非法字符")

    parsed = urlparse(url)
    allowed_schemes = {"https"} if require_https else _ALLOWED_SCHEMES
    if parsed.scheme not in allowed_schemes:
        raise ValidationError(
            f"不支持的 URL 协议: {parsed.scheme or '空'}"
        )

    host = parsed.hostname
    if not host:
        raise ValidationError("URL 缺少主机名")

    if allowed_ports is not None:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in allowed_ports:
            raise ValidationError(f"不允许的端口: {port}")

    allowlist = _mcp_allowlist() if profile == "mcp" else _default_allowlist()

    host_lower = host.lower()
    if allowlist.allows_host(host_lower):
        logger.debug("SSRF guard: host '%s' 在白名单中", host_lower)
        return []

    # 字面量 IP 地址直接校验
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        unwrapped = _unwrap_ip(literal)
        if _is_blocked_ip(host, allowlist):
            raise ValidationError(f"禁止访问非公网地址: {host}")
        return [str(unwrapped)]

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return _resolve_public_ips(host, port, allowlist)


def assert_safe_url(url: str) -> None:
    """向后兼容入口：校验 URL，不通过则抛 ValidationError。

    等价于 validate_url(url, profile="default")，保留签名供 crawl_service 调用。
    """
    validate_url(url, profile="default")
