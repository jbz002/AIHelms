"""AI Hub 出站调用验签（HMAC-SHA256，v1 协议）。

与 AI Hub docs/sub-app-auth-guide.md 方式六协议对齐：
签名串 = "v1\n{timestamp}\n{METHOD}\n{path_with_query}\n{sha256_hex(body)}\n{on_behalf_of 或空}"
path_with_query = request.url.path + ("?" + query)——path 解码后、query 保持原始编码
（Starlette request.url 语义）。密钥为对称共享密钥，空 = 集成通道关闭。
"""

import hashlib
import hmac
import logging
import time

from fastapi import HTTPException, Request, status

from core.config import settings

logger = logging.getLogger(__name__)

TIMESTAMP_TOLERANCE_SECONDS = 300


async def verify_aihub(request: Request) -> str | None:
    """验签依赖。通过返回 On-Behalf-Of 用户 ID（服务调用时为 None），失败抛 401。"""
    secret = settings.aihub_integration_hmac_secret
    if not secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "集成通道未启用")

    ts = request.headers.get("X-AIHub-Timestamp", "")
    received = request.headers.get("X-AIHub-Signature", "")
    on_behalf_of = request.headers.get("X-AIHub-On-Behalf-Of")

    try:
        ts_int = int(ts)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少有效时间戳")
    if abs(time.time() - ts_int) > TIMESTAMP_TOLERANCE_SECONDS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请求已过期")

    body = await request.body()
    path_with_query = request.url.path + (
        "?" + request.url.query if request.url.query else ""
    )
    message = "\n".join(
        [
            "v1",
            ts,
            request.method.upper(),
            path_with_query,
            hashlib.sha256(body or b"").hexdigest(),
            on_behalf_of or "",
        ]
    ).encode()
    expected = "v1=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    # compare_digest 收到非 ASCII str 会抛 TypeError（导致 500 而非 401），先校验
    if not received or not received.isascii():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "签名无效")
    if not hmac.compare_digest(expected, received):
        logger.warning("aihub hmac verify failed: path=%s", request.url.path)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "签名无效")
    return on_behalf_of
