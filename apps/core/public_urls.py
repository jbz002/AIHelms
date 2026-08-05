"""按当前请求解析对外公共地址。

接入指南里展示给用户的 LiteLLM / 平台地址需随「用户访问 web 端所用的主机名」变化，
否则服务器换 LAN IP 后旧地址失效。优先从请求 Host 头取主机名重拼（浏览器能打开 web 端
说明该主机名可达）。

端口策略：
  - 平台地址（web 端同主机）：优先复用浏览器实际访问的端口（既然能打开 web 端，该端口
    必然可达），请求头无端口时才按 ``WEB_PORT`` 配置补。早期实现先剥端口再用配置重拼，
    当实际访问端口与 ``WEB_PORT``（默认 80）不一致时下载 URL 会指向错误端口被拒。
  - loopback 主机名（localhost/127.0.0.1）不可对外：host 换成本机 LAN IP，但**浏览器端口
    仍然保留**。开发态常用 ``localhost:4002`` 打开 web 端，若端口也回退到 ``WEB_PORT=80``
    会生成无端口 URL（指向 80，本机无服务），下载被拒。
  - LiteLLM 地址：LiteLLM 是独立服务、固定端口，不复用浏览器端口，统一用 ``LITELLM_PORT``。

回退策略：请求主机名缺失或 loopback（如开发态用 localhost 打开）时——
  - 宿主机环境（非容器，即 dev）：探测本机当前 LAN IP，换 wifi 自动跟着变；
  - 容器环境（prod）：直接用 settings 配置值，避免探测到容器内网 IP。
"""

import os
import socket

from fastapi import Request

from core.config import settings

_LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _split_netloc(netloc: str) -> tuple[str, str | None]:
    """拆 netloc 为 (host, port|None)，支持 IPv6 ``[host]:port`` 形式。"""
    netloc = netloc.strip()
    if netloc.startswith("["):
        end = netloc.find("]")
        if end == -1:
            return netloc, None
        host = netloc[1:end]
        rest = netloc[end + 1 :]
        return (host, rest[1:]) if rest.startswith(":") else (host, None)
    if ":" in netloc:
        host, port = netloc.rsplit(":", 1)
        return host, (port or None)
    return netloc, None


def _request_raw_host_port(request: Request) -> tuple[str, str | None] | None:
    """请求头里的原始 (host, port)，不做 loopback 过滤；无头返回 None。"""
    raw = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    if not raw.strip():
        return None
    return _split_netloc(raw)


def _request_host_port(request: Request) -> tuple[str, str | None] | None:
    """对客户端可达的 (host, port)，保留端口。loopback 主机名视为不可用（返回 None）。

    LiteLLM 解析用本函数（独立固定端口，不需要 loopback 端口保留）；平台地址解析需保留
    loopback 请求的浏览器端口，故直接用 ``_request_raw_host_port`` 自行处理。
    """
    raw = _request_raw_host_port(request)
    if raw and raw[0].lower() not in _LOOPBACK:
        return raw
    return None


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


def _join_netloc(host: str, port: str | None) -> str:
    """拼 URL 的 host[:port]，IPv6 主机名加方括号。"""
    if port is None:
        return host
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def resolve_litellm_public_url(request: Request) -> str:
    """对外的 LiteLLM 地址：请求主机名 + LITELLM_PORT（独立服务，不复用浏览器端口）。"""
    hp = _request_host_port(request)
    host = hp[0] if hp else _fallback_host()
    if not host:
        return settings.litellm_public_url.rstrip("/")
    return f"{_scheme(request)}://{_join_netloc(host, str(settings.litellm_port))}"


def resolve_platform_public_url(request: Request) -> str:
    """平台对外地址（web 端同主机）。

    - 可信 host（非 loopback）：直接用，缺端口时按 ``WEB_PORT`` 补（80 省略）。
    - loopback host（localhost/127.0.0.1）：host 不可对外，换成 LAN IP/配置；但**保留浏览器
      实际端口**（localhost:4002 → LAN_IP:4002），避免回退到 80 生成不可达 URL。
    - 完全无 host 头：回退到 LAN IP/配置 + ``WEB_PORT``。
    """
    raw = _request_raw_host_port(request)
    browser_port: str | None = None
    if raw:
        host, port = raw
        if host.lower() not in _LOOPBACK:
            if port is None and settings.web_port != 80:
                port = str(settings.web_port)
            return f"{_scheme(request)}://{_join_netloc(host, port)}"
        browser_port = port  # loopback：host 弃用，端口保留

    host = _fallback_host()
    if not host:
        return settings.platform_public_url.rstrip("/")
    port = (
        browser_port
        if browser_port
        else (None if settings.web_port == 80 else str(settings.web_port))
    )
    return f"{_scheme(request)}://{_join_netloc(host, port)}"
