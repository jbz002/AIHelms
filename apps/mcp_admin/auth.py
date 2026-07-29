"""管理员 MCP 鉴权：平台 API Key 校验。"""

from fastmcp.server.auth import AccessToken, TokenVerifier

from core.deps import validate_api_key
from exceptions import UnauthorizedError

ADMIN_CLIENT_ID = "aihelms-admin-mcp"


class AdminKeyVerifier(TokenVerifier):
    """用平台 API Key（ak- 前缀）做 MCP Bearer 鉴权。

    verify_token 成功返回带 user_id/api_key_id 的 AccessToken；失败返回 None，
    fastmcp 自动回 401。
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            ident = await validate_api_key(token)
        except UnauthorizedError:
            return None
        return AccessToken(
            token=token,
            client_id=ADMIN_CLIENT_ID,
            scopes=[],
            subject=str(ident["user_id"]),
            claims={
                "user_id": ident["user_id"],
                "api_key_id": ident["id"],
                "username": ident["username"],
            },
        )
