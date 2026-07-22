"""S7 阶段一 · CLI 分发通道 Scoped Token 服务。

复用 ai_keys 表（token_kind='cli' 判别），自生成 sk_cli_ 前缀 token，sha256 哈希入库，
scope_json 细粒度分权。与 LLM 明文 key（litellm_key_id）隔离：CLI 行 litellm_key_id 为 NULL。
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError, ValidationError
from models.db import AiKey
from repositories import ai_key_repo

logger = logging.getLogger(__name__)

TOKEN_PREFIX_LITERAL = "sk_cli_"
# 可选 scope：skill:* 为通配
SCOPE_OPTIONS = [
    "skill:search",
    "skill:read",
    "skill:install",
    "skill:publish",
    "skill:tag:read",
    "skill:label:read",
    "skill:*",
]
_VALID_SCOPES = set(SCOPE_OPTIONS)


def _generate_token() -> tuple[str, str, str]:
    """生成 CLI token。

    Returns:
        (full_token, token_prefix, token_hash)
        - full_token: 完整 token（仅返回一次）
        - token_prefix: 'sk_cli_' + 8 hex（展示用，不敏感）
        - token_hash: sha256(full_token)（持久化校验）
    """
    prefix_part = secrets.token_hex(4)  # 8 hex
    secret_part = secrets.token_hex(16)  # 32 hex
    full_token = f"{TOKEN_PREFIX_LITERAL}{prefix_part}{secret_part}"
    token_prefix = f"{TOKEN_PREFIX_LITERAL}{prefix_part}"
    token_hash = hashlib.sha256(full_token.encode("utf-8")).hexdigest()
    return full_token, token_prefix, token_hash


def hash_cli_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _validate_scopes(scopes: list[str]) -> list[str]:
    invalid = [s for s in scopes if s not in _VALID_SCOPES]
    if invalid:
        raise ValidationError(f"不支持的 scope: {invalid}")
    return scopes


def _serialize(token: AiKey, *, include_key: bool = False, raw_key: str = "") -> dict:
    data = {
        "id": token.id,
        "name": token.name,
        "description": token.description,
        "token_kind": token.token_kind,
        "token_prefix": token.token_prefix,
        "scopes": token.scope_json or [],
        "owner_type": token.owner_type,
        "owner_id": token.owner_id,
        "is_active": token.is_active,
        "created_by": token.created_by,
        "created_at": token.created_at.isoformat() if token.created_at else None,
        "updated_at": token.updated_at.isoformat() if token.updated_at else None,
        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "last_used_at": (
            token.last_used_at.isoformat() if token.last_used_at else None
        ),
    }
    if include_key:
        data["key_value"] = raw_key
    return data


async def create_token(
    session: AsyncSession,
    *,
    name: str,
    description: str,
    scopes: list[str],
    owner_id: int,
    owner_type: str = "user",
    expires_at: datetime | None = None,
    created_by: int | None = None,
) -> tuple[dict, str]:
    full_token, token_prefix, token_hash = _generate_token()
    token = AiKey(
        name=name,
        description=description,
        key_type="cli",
        owner_type=owner_type,
        owner_id=owner_id,
        token_kind="cli",
        token_hash=token_hash,
        token_prefix=token_prefix,
        scope_json=_validate_scopes(scopes),
        litellm_key_id=None,
        is_active=True,
        expires_at=expires_at,
        created_by=created_by,
    )
    token = await ai_key_repo.create(session, token)
    await session.commit()
    logger.info(
        "cli token created",
        extra={"token_id": token.id, "owner_id": owner_id, "scopes": scopes},
    )
    return _serialize(token, include_key=True, raw_key=full_token), full_token


async def list_tokens(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    owner_id: int | None = None,
) -> dict:
    total = await ai_key_repo.count_cli_tokens(session, owner_id)
    tokens = await ai_key_repo.find_cli_tokens(session, page, page_size, owner_id)
    return {
        "items": [_serialize(t) for t in tokens],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_token(session: AsyncSession, token_id: int) -> dict:
    token = await ai_key_repo.find_by_id(session, token_id)
    if not token or token.token_kind != "cli":
        raise NotFoundError("cli_token", token_id)
    return _serialize(token)


async def update_token(
    session: AsyncSession,
    token_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    scopes: list[str] | None = None,
    is_active: bool | None = None,
) -> dict:
    token = await ai_key_repo.find_by_id(session, token_id)
    if not token or token.token_kind != "cli":
        raise NotFoundError("cli_token", token_id)
    if name is not None:
        token.name = name
    if description is not None:
        token.description = description
    if scopes is not None:
        token.scope_json = _validate_scopes(scopes)
    if is_active is not None:
        token.is_active = is_active
    await session.commit()
    await session.refresh(token)
    return _serialize(token)


async def revoke_token(session: AsyncSession, token_id: int) -> None:
    token = await ai_key_repo.find_by_id(session, token_id)
    if not token or token.token_kind != "cli":
        raise NotFoundError("cli_token", token_id)
    token.is_active = False
    await session.commit()
