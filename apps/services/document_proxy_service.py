"""接口调试器 Try-it-out 后端代理。

调试场景目标 server 多在内网/未配 CORS，由后端转发规避浏览器 CORS 限制。

安全边界（SSRF）：
- method 白名单（GET/POST/PUT/DELETE/PATCH）
- 仅 http(s)
- DNS 解析后拦截 loopback（127/8、::1）与 link-local（169.254/16，含云元数据 169.254.169.254）
- 私网 LAN 放行——调试内网 API 为核心用例，威胁模型限定为已认证 admin
- 超时 + 响应体大小上限（超则截断）
- 不跟随重定向（避免重定向绕过 IP 校验）

目标自身 4xx/5xx 为有效结果，原样回传，不抛；仅网络层故障（超时/连接失败）抛 ValidationError。
"""

import ipaddress
import logging
import socket
import time
from urllib.parse import urlparse

import httpx

from core.config import settings
from exceptions import ValidationError

logger = logging.getLogger(__name__)

_ALLOWED_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),
]


def _validate_method(method: str) -> str:
    upper = method.upper()
    if upper not in _ALLOWED_METHODS:
        raise ValidationError(f"不允许的 HTTP 方法: {method}")
    return upper


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError("仅支持 http/https 协议")
    host = parsed.hostname
    if not host:
        raise ValidationError("URL 缺少主机名")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValidationError(f"无法解析主机名: {host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        for net in _BLOCKED_NETWORKS:
            if ip in net:
                raise ValidationError(f"禁止访问的地址: {ip}")


async def proxy_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: str | None = None,
) -> dict[str, object]:
    upper_method = _validate_method(method)
    _validate_url(url)

    timeout = httpx.Timeout(settings.document_proxy_timeout_seconds)
    max_bytes = settings.document_proxy_max_bytes
    start = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream(
                upper_method, url, headers=headers or {}, content=body
            ) as resp:
                status = resp.status_code
                reason = resp.reason_phrase
                resp_headers = dict(resp.headers)
                content_type = resp.headers.get("content-type", "")
                collected = bytearray()
                truncated = False
                async for chunk in resp.aiter_bytes():
                    collected.extend(chunk)
                    if len(collected) >= max_bytes:
                        del collected[max_bytes:]
                        truncated = True
                        break
    except httpx.TimeoutException as e:
        raise ValidationError(
            f"请求超时（{settings.document_proxy_timeout_seconds}s）"
        ) from e
    except httpx.RequestError as e:
        raise ValidationError(f"请求失败: {e}") from e

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "document proxy %s %s -> %s, %d bytes%s, %dms",
        upper_method,
        url,
        status,
        len(collected),
        " (truncated)" if truncated else "",
        duration_ms,
    )
    return {
        "status": status,
        "status_text": reason,
        "headers": resp_headers,
        "body": collected.decode("utf-8", errors="replace"),
        "content_type": content_type,
        "duration_ms": duration_ms,
        "truncated": truncated,
    }
