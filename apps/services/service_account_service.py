"""服务账号与委托授权（P2 身份与委托）。

两类机器调用必须区分（02 §6 / 03 §7）：

- **机器自身**（夜间统计等）：用服务账号自己的授权，不借用任何员工身份；
- **代表人类**（钉钉机器人代员工查数据）：必须有一条未过期的委托授权，
  且执行时取「用户授权 ∩ 委托范围 ∩ server.allow_machine_delegation」。

本模块只负责身份与委托的存取；交集判定在 PDP（`mcp_pdp`）里做。
令牌沿用 CLI token 的做法：`sk_sa_` 前缀 + sha256 入库，明文只在签发时返回一次。
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import DelegationGrant, ServiceAccount
from repositories import mcp_authz_repo, mcp_repo, service_account_repo, user_repo

logger = logging.getLogger(__name__)

TOKEN_PREFIX_LITERAL = "sk_sa_"
KINDS = ("bot", "task", "agent")
TARGET_TYPES = ("server", "toolset")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_token() -> tuple[str, str, str]:
    """返回 (完整令牌, 展示前缀, sha256)。完整令牌只返回一次。"""
    prefix_part = secrets.token_hex(4)
    secret_part = secrets.token_hex(16)
    full_token = f"{TOKEN_PREFIX_LITERAL}{prefix_part}{secret_part}"
    return (
        full_token,
        f"{TOKEN_PREFIX_LITERAL}{prefix_part}",
        hashlib.sha256(full_token.encode("utf-8")).hexdigest(),
    )


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def serialize(sa: ServiceAccount) -> dict:
    return {
        "id": sa.id,
        "name": sa.name,
        "kind": sa.kind,
        "description": sa.description,
        "owner_user_id": sa.owner_user_id,
        "token_prefix": sa.token_prefix,
        "status": sa.status,
        "expires_at": sa.expires_at.isoformat() if sa.expires_at else None,
        "last_used_at": sa.last_used_at.isoformat() if sa.last_used_at else None,
        "created_by": sa.created_by,
        "created_at": sa.created_at.isoformat() if sa.created_at else None,
    }


def serialize_delegation(grant: DelegationGrant) -> dict:
    return {
        "id": grant.id,
        "service_account_id": grant.service_account_id,
        "user_id": grant.user_id,
        "target_type": grant.target_type,
        "target_id": grant.target_id,
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "granted_via": grant.granted_via,
        "granted_by": grant.granted_by,
        "reason": grant.reason,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "revoked_by": grant.revoked_by,
        "created_at": grant.created_at.isoformat() if grant.created_at else None,
    }


# ─── 服务账号 ────────────────────────────────────────────────────────────────


def _validate_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ValidationError("不支持的服务账号类型：" + kind)


async def create_service_account(
    session: AsyncSession,
    *,
    name: str,
    kind: str = "bot",
    description: str = "",
    owner_user_id: int | None = None,
    expires_at: datetime | None = None,
    created_by: int | None = None,
) -> tuple[ServiceAccount, str]:
    """创建服务账号，返回 (账号, 明文令牌)。令牌之后不可再取回。"""
    name = (name or "").strip()
    if not name:
        raise ValidationError("服务账号名称不能为空")
    _validate_kind(kind)
    if await service_account_repo.find_by_name(session, name) is not None:
        raise ConflictError("服务账号名称已存在：" + name)
    if owner_user_id is not None:
        if await user_repo.find_user_by_id(session, owner_user_id) is None:
            raise NotFoundError("user", owner_user_id)

    full_token, prefix, token_hash = _generate_token()
    sa = ServiceAccount(
        name=name,
        kind=kind,
        description=description or "",
        owner_user_id=owner_user_id,
        token_prefix=prefix,
        token_hash=token_hash,
        status="active",
        expires_at=expires_at,
        created_by=created_by,
    )
    await service_account_repo.create(session, sa)
    return sa, full_token


async def rotate_token(
    session: AsyncSession, sa_id: int
) -> tuple[ServiceAccount, str]:
    """轮换令牌：旧令牌立即失效（同一行换 hash）。"""
    sa = await service_account_repo.find_by_id(session, sa_id)
    if sa is None:
        raise NotFoundError("service_account", sa_id)
    full_token, prefix, token_hash = _generate_token()
    sa.token_prefix = prefix
    sa.token_hash = token_hash
    await session.flush()
    await session.refresh(sa)
    return sa, full_token


async def get_service_account(session: AsyncSession, sa_id: int) -> ServiceAccount:
    sa = await service_account_repo.find_by_id(session, sa_id)
    if sa is None:
        raise NotFoundError("service_account", sa_id)
    return sa


async def list_service_accounts(session: AsyncSession) -> list[ServiceAccount]:
    return await service_account_repo.list_service_accounts(session)


async def update_service_account(
    session: AsyncSession, sa_id: int, **fields
) -> ServiceAccount:
    sa = await get_service_account(session, sa_id)
    new_name = fields.get("name")
    if new_name:
        new_name = new_name.strip()
        other = await service_account_repo.find_by_name(session, new_name)
        if other is not None and other.id != sa.id:
            raise ConflictError("服务账号名称已存在：" + new_name)
        sa.name = new_name
    if fields.get("kind") is not None:
        _validate_kind(fields["kind"])
        sa.kind = fields["kind"]
    if fields.get("status") is not None:
        if fields["status"] not in ("active", "disabled"):
            raise ValidationError("status 只能是 active / disabled")
        sa.status = fields["status"]
    if fields.get("description") is not None:
        sa.description = fields["description"]
    if fields.get("expires_at") is not None:
        sa.expires_at = fields["expires_at"]
    if fields.get("owner_user_id") is not None:
        if await user_repo.find_user_by_id(session, fields["owner_user_id"]) is None:
            raise NotFoundError("user", fields["owner_user_id"])
        sa.owner_user_id = fields["owner_user_id"]
    await session.flush()
    await session.refresh(sa)
    return sa


async def delete_service_account(session: AsyncSession, sa_id: int) -> None:
    sa = await get_service_account(session, sa_id)
    await service_account_repo.delete(session, sa)
    await session.flush()


async def verify_token(session: AsyncSession, raw_token: str) -> ServiceAccount | None:
    """校验服务账号令牌：不存在 / 停用 / 过期一律返回 None（调用方 fail-closed）。"""
    raw_token = (raw_token or "").strip()
    if not raw_token.startswith(TOKEN_PREFIX_LITERAL):
        return None
    sa = await service_account_repo.find_by_token_hash(session, hash_token(raw_token))
    if sa is None or sa.status != "active":
        return None
    if sa.expires_at is not None and sa.expires_at <= _now():
        return None
    return sa


# ─── 委托授权 ────────────────────────────────────────────────────────────────


async def _validate_target(
    session: AsyncSession, target_type: str, target_id: int
) -> None:
    if target_type not in TARGET_TYPES:
        raise ValidationError("不支持的委托目标类型：" + target_type)
    if target_type == "server":
        if await mcp_repo.find_server_by_id(session, target_id) is None:
            raise NotFoundError("mcp_server", target_id)
    elif await mcp_authz_repo.find_toolset_by_id(session, target_id) is None:
        raise NotFoundError("mcp_toolset", target_id)


async def grant_delegation(
    session: AsyncSession,
    *,
    service_account_id: int,
    user_id: int,
    target_type: str,
    target_id: int,
    expires_at: datetime | None = None,
    granted_via: str = "manual",
    granted_by: int | None = None,
    reason: str | None = None,
) -> DelegationGrant:
    sa = await service_account_repo.find_by_id(session, service_account_id)
    if sa is None:
        raise NotFoundError("service_account", service_account_id)
    if sa.status != "active":
        raise ValidationError("服务账号已停用，不能新增委托")
    if await user_repo.find_user_by_id(session, user_id) is None:
        raise NotFoundError("user", user_id)
    await _validate_target(session, target_type, target_id)

    existing = await service_account_repo.find_active_delegation(
        session, service_account_id, user_id, target_type, target_id
    )
    if existing is not None:
        raise ConflictError("同一服务账号在同一目标上已有生效委托")
    if expires_at is not None and expires_at <= _now():
        raise ValidationError("委托过期时间必须晚于当前时间")

    grant = DelegationGrant(
        service_account_id=service_account_id,
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        expires_at=expires_at,
        granted_via=granted_via,
        granted_by=granted_by,
        reason=reason,
    )
    return await service_account_repo.create_delegation(session, grant)


async def revoke_delegation(
    session: AsyncSession, grant_id: int, revoked_by: int | None = None
) -> DelegationGrant:
    grant = await service_account_repo.find_delegation_by_id(session, grant_id)
    if grant is None:
        raise NotFoundError("delegation_grant", grant_id)
    if grant.revoked_at is None:
        await service_account_repo.revoke_delegation(session, grant, revoked_by)
    return grant


async def list_delegations(
    session: AsyncSession,
    service_account_id: int | None = None,
    user_id: int | None = None,
    include_revoked: bool = False,
) -> list[DelegationGrant]:
    return await service_account_repo.list_delegations(
        session,
        service_account_id=service_account_id,
        user_id=user_id,
        include_revoked=include_revoked,
    )


async def delegation_allows(
    session: AsyncSession,
    service_account_id: int,
    user_id: int,
    server_id: int,
    tool_name: str | None,
) -> bool:
    """该服务账号此刻是否被 user 允许在该 server 的该工具上代表他。

    server 级委托覆盖其全部工具；toolset 级委托只覆盖束内属于该 server 的工具。
    """
    grants = await service_account_repo.active_delegations_for(
        session, service_account_id, user_id
    )
    if not grants:
        return False
    toolset_cache: dict[int, list] = {}
    for grant in grants:
        if grant.target_type == "server" and grant.target_id == server_id:
            return True
        if grant.target_type != "toolset":
            continue
        if grant.target_id not in toolset_cache:
            toolset = await mcp_authz_repo.find_toolset_by_id(session, grant.target_id)
            toolset_cache[grant.target_id] = (
                list(toolset.items or []) if toolset else []
            )
        for item in toolset_cache[grant.target_id]:
            if not isinstance(item, dict):
                continue
            if item.get("server_id") != server_id:
                continue
            if tool_name is None or item.get("tool_name") == tool_name:
                return True
    return False
