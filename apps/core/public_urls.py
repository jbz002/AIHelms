"""按当前请求解析对外公共地址。

接入指南里展示给用户的 LiteLLM / 平台地址需随「用户访问 web 端所用的主机名」变化，
否则服务器换 LAN IP 后旧地址失效。优先从请求 Host 头取主机名重拼（浏览器能打开 web 端
说明该主机名可达）。

回退策略：请求主机名缺失或 loopback（如开发态用 localhost 打开）时——
  - 宿主机环境（非容器，即 dev）：探测本机当前 LAN IP，换 wifi 自动跟着变；
  - 容器环境（prod）：直接用 settings 配置值，避免探测到容器内网 IP。
"""

import os
import socket

from fastapi import Request

from core.config import settings

_LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _request_host(request: Request) -> str | None:
    """从请求头取对客户端可达的主机名，剥离端口。loopback 视为不可用。"""
    raw = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    host = raw.strip()
    if not host:
        return None
    # IPv6 形如 [::1]:8080
    if host.startswith("["):
        end = host.find("]")
        host = host[1:end] if end != -1 else host
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    if host.lower() in _LOOPBACK:
        return None
    return host


def _detect_lan_ip() -> str | None:
    """探测本机当前默认路由出口的 IPv4（UDP connect 法，不发包）。"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return None
    return None if ip in _LOOPBACK else ip


def _fallback_host() -> str | None:
    """请求拿不到可用主机名时的回退：宿主探测 LAN IP，容器内不探测。"""
    if os.path.exists("/.dockerenv"):
        return None
    return _detect_lan_ip()


def _scheme(request: Request) -> str:
    return request.headers.get("x-forwarded-proto") or "http"


def _netloc(host: str, port_suffix: str) -> str:
    """拼 URL 的 host[:port]，IPv6 主机名加方括号。"""
    return f"[{host}]{port_suffix}" if ":" in host else f"{host}{port_suffix}"


def resolve_litellm_public_url(request: Request) -> str:
    """对外的 LiteLLM 地址：请求主机名 + LITELLM_PORT。"""
    host = _request_host(request) or _fallback_host()
    if not host:
        return settings.litellm_public_url.rstrip("/")
    netloc = _netloc(host, f":{settings.litellm_port}")
    return f"{_scheme(request)}://{netloc}"


def resolve_platform_public_url(request: Request) -> str:
    """平台对外地址（web 端同主机）：请求主机名 + WEB_PORT（80 省略）。"""
    host = _request_host(request) or _fallback_host()
    if not host:
        return settings.platform_public_url.rstrip("/")
    port_suffix = "" if settings.web_port == 80 else f":{settings.web_port}"
    netloc = _netloc(host, port_suffix)
    return f"{_scheme(request)}://{netloc}"
