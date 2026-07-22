import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Query, Request
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from core.api_key_utils import hash_api_key, looks_like_api_key
from core.config import settings
from core.database import async_session
from core.security import ALGORITHM
from repositories import ai_key_repo, api_key_repo
from services import cli_token_service

logger = logging.getLogger(__name__)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证 token")
    token = auth_header.split(" ", 1)[1]

    if looks_like_api_key(token):
        identity = await _authenticate_api_key(token)
    else:
        identity = _authenticate_jwt(token)

    request.state.current_user = identity
    return identity


def _authenticate_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="token 无效")
    return {
        "id": int(user_id),
        "username": payload.get("username", ""),
        "identity_type": "user",
        "is_admin": payload.get("is_admin", False),
        "permissions": payload.get("permissions", []),
    }


async def _authenticate_api_key(token: str) -> dict:
    key_hash = hash_api_key(token)
    async with async_session() as session:
        api_key = await api_key_repo.find_by_hash(session, key_hash)
    if not api_key or not api_key.is_active:
        raise HTTPException(status_code=401, detail="API Key 无效或已禁用")
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="API Key 已过期")

    # 异步更新 last_used_at，不阻塞请求
    asyncio.create_task(_update_last_used(api_key.id))

    return {
        "id": api_key.id,
        "username": api_key.name,
        "identity_type": "api_key",
        "is_admin": True,
        "permissions": [],
    }


async def _update_last_used(key_id: int) -> None:
    try:
        async with async_session() as session:
            await api_key_repo.touch_last_used(session, key_id)
    except Exception:  # noqa: BLE001
        logger.warning("update api key last_used failed", exc_info=True)


def require_permission(permission_code: str):
    async def checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["is_admin"]:
            return current_user
        if permission_code not in current_user["permissions"]:
            raise HTTPException(status_code=403, detail="权限不足")
        return current_user

    return checker


async def get_ai_key_identity(
    request: Request,
    token: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """从 query param ?token= 或 Authorization: Bearer 提取 AI Key，验证身份。"""
    raw_token = token
    if not raw_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            raw_token = auth_header.split(" ", 1)[1]

    if not raw_token:
        raise HTTPException(status_code=401, detail="未提供 AI Key 认证凭证")

    ai_key = await ai_key_repo.find_by_litellm_key_id(session, raw_token)
    if not ai_key:
        raise HTTPException(status_code=401, detail="AI Key 无效")
    if not ai_key.is_active:
        raise HTTPException(status_code=401, detail="AI Key 已禁用")
    if ai_key.expires_at and ai_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="AI Key 已过期")

    return {
        "ai_key_id": ai_key.id,
        "user_id": ai_key.owner_id,
        "owner_type": ai_key.owner_type,
        "owner_id": ai_key.owner_id,
        "skills": ai_key.skills or [],
    }


# ─── CLI scoped token（S7 阶段一）─────────────────────────────────────────────

CLI_TOKEN_PREFIX = "sk_cli_"


def _extract_cli_token(request: Request, token: str | None) -> str | None:
    raw = token
    if not raw:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            raw = auth_header.split(" ", 1)[1]
    return raw


async def get_cli_token_identity(
    request: Request,
    token: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """从 ?token= 或 Authorization: Bearer 提取 CLI scoped token，哈希校验身份。

    与 get_ai_key_identity 隔离：仅接受 sk_cli_ 前缀 token，按 sha256 哈希查 cli 行。
    """
    raw_token = _extract_cli_token(request, token)
    if not raw_token:
        raise HTTPException(status_code=401, detail="未提供 CLI 令牌")
    if not raw_token.startswith(CLI_TOKEN_PREFIX):
        raise HTTPException(status_code=401, detail="CLI 令牌无效")

    cli_token = await ai_key_repo.find_cli_by_hash(
        session, cli_token_service.hash_cli_token(raw_token)
    )
    if not cli_token:
        raise HTTPException(status_code=401, detail="CLI 令牌无效")
    if not cli_token.is_active:
        raise HTTPException(status_code=401, detail="CLI 令牌已禁用")
    if cli_token.expires_at and cli_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="CLI 令牌已过期")

    asyncio.create_task(_touch_cli_last_used(cli_token.id))

    return {
        "ai_key_id": cli_token.id,
        "owner_id": cli_token.owner_id,
        "owner_type": cli_token.owner_type,
        "scopes": cli_token.scope_json or [],
    }


async def _touch_cli_last_used(key_id: int) -> None:
    try:
        async with async_session() as session:
            await ai_key_repo.touch_cli_last_used(session, key_id)
    except Exception:  # noqa: BLE001
        logger.warning("update cli token last_used failed", exc_info=True)


def require_cli_scope(code: str):
    """CLI scope 校验依赖：code 命中 scopes 或持有通配 skill:* 则放行，否则 403。"""

    async def checker(identity: dict = Depends(get_cli_token_identity)) -> dict:
        scopes = identity.get("scopes", [])
        if code in scopes or "skill:*" in scopes:
            return identity
        raise HTTPException(status_code=403, detail="scope 不足")

    return checker
