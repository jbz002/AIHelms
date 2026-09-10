"""AI Hub 凭证自省验证（方式七：被其他子应用直连调用）。

与 AI Hub docs/sub-app-calling-guide.md §四协议对齐：
调用方 B 持 AI Hub 签发凭证（用户 access_token 或 AppAPIKey）直连调我们，
本依赖把 Bearer 凭证原样转发给 AI Hub /api/v1/auth/introspect 验证，
凭返回的调用方身份（caller_type / user_id / app_roles）放行。

无需共享密钥；凭证验证与授权判定（allowed_target_apps、访问白名单、调用日志）
均由 AI Hub 集中完成。AI Hub 不可达时 fail-closed（401）。
"""

import logging

import httpx
from fastapi import HTTPException, Request, status

from core.config import settings

logger = logging.getLogger(__name__)

INTROSPECT_TIMEOUT_SECONDS = 5


async def _introspect(
    authorization: str, target_path: str, method: str
) -> tuple[int, dict]:
    """调 AI Hub 自省端点，返回 (http_status, body_json)。异常由调用方处理。"""
    async with httpx.AsyncClient(timeout=INTROSPECT_TIMEOUT_SECONDS) as client:
        resp = await client.get(
            f"{settings.ai_hub_url.rstrip('/')}/api/v1/auth/introspect",
            params={
                "app_code": settings.ai_hub_app_code,
                "target_path": target_path,
                "method": method,
            },
            headers={"Authorization": authorization},
        )
        return resp.status_code, resp.json()


async def verify_aihub_credential(request: Request) -> dict:
    """验证请求方的 AI Hub 凭证（直连 + 自省模式）。

    返回自省结果（valid / caller_type / user_id / app_code / app_roles），失败抛 401。
    caller_type 的业务校验（个人数据须 user 态）由调用方路由判断。
    """
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少 AI Hub 凭证")
    if not settings.ai_hub_url:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "AI Hub 集成未配置")

    try:
        http_status, body = await _introspect(
            authorization, request.url.path, request.method
        )
    except httpx.HTTPError:
        logger.warning("aihub introspect unreachable: path=%s", request.url.path)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "凭证验证服务不可用")

    if http_status != 200 or not body.get("valid"):
        logger.warning(
            "aihub introspect rejected: path=%s status=%s",
            request.url.path,
            http_status,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "凭证无效或无权限")
    return body
