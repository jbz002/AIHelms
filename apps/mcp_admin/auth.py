"""管理员 MCP 鉴权：平台 API Key 校验 + 管理员角色校验。"""

from fastmcp.server.auth import AccessToken, TokenVerifier

from core.database import async_session
from core.deps import validate_api_key
from exceptions import UnauthorizedError
from repositories import user_repo

ADMIN_CLIENT_ID = "aihelms-admin-mcp"


class AdminKeyVerifier(TokenVerifier):
    """用平台 API Key（ak- 前缀）做 MCP Bearer 鉴权，并校验调用者为活跃管理员。

    verify_token 成功返回带 user_id/api_key_id/username 的 AccessToken；失败返回 None，
    fastmcp 自动回 401。validate_api_key 已按签发环节假定 is_admin，此处再查 user 表
    做运行时校验（M0 前置基建），杜绝被降权/禁用后仍可用旧 Key。
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            ident = await validate_api_key(token)
        except UnauthorizedError:
            return None
        user_id = ident["user_id"]
        async with async_session() as session:
            user = await user_repo.find_user_by_id(session, user_id)
        if not user or not user.is_active or not (user.is_admin or user.is_super_admin):
            return None
        return AccessToken(
            token=token,
            client_id=ADMIN_CLIENT_ID,
            scopes=[],
            subject=str(user_id),
            claims={
                "user_id": user_id,
                "api_key_id": ident["id"],
                "username": user.username,
                "is_super_admin": user.is_super_admin,
            },
        )
