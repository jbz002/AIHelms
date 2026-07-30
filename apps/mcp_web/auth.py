"""用户自助 MCP 鉴权：平台 API Key 校验 + 活跃用户校验（不要求 admin）。"""

from fastmcp.server.auth import AccessToken, TokenVerifier

from core.database import async_session
from core.deps import validate_api_key
from exceptions import UnauthorizedError
from repositories import user_repo

USER_CLIENT_ID = "aihelms-web-mcp"


class UserKeyVerifier(TokenVerifier):
    """用平台 API Key（ak- 前缀）做 MCP Bearer 鉴权，校验调用者为活跃用户。

    与 AdminKeyVerifier 的区别：不要求 is_admin。用户经 /api-keys/my 自创的 key，
    其创建者非 admin → AdminKeyVerifier 拒（admin-mcp 不可用），本 verifier 收。
    verify_token 失败返回 None（fastmcp 自动回 401）。
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            ident = await validate_api_key(token)
        except UnauthorizedError:
            return None
        user_id = ident["user_id"]
        async with async_session() as session:
            user = await user_repo.find_user_by_id(session, user_id)
        if not user or not user.is_active:
            return None
        return AccessToken(
            token=token,
            client_id=USER_CLIENT_ID,
            scopes=[],
            subject=str(user_id),
            claims={
                "user_id": user_id,
                "api_key_id": ident["id"],
                "username": user.username,
                "is_admin": ident["is_admin"],
            },
        )
