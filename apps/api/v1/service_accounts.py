"""服务账号与委托授权 API（P2 身份与委托）。

令牌明文只在创建/轮换的响应里出现一次，之后任何接口都不返回；列表只给 `token_prefix`。
委托授权变更会递增策略版本（供 PDP 缓存失效）。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from repositories import mcp_authz_repo
from services import service_account_service

router = APIRouter(prefix="/service-accounts", tags=["机器身份"])


class ServiceAccountCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    kind: str = Field("bot", pattern="^(bot|task|agent)$")
    description: str = Field("", max_length=500)
    owner_user_id: int | None = Field(None, ge=1)
    expires_at: datetime | None = None


class ServiceAccountUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    kind: str | None = Field(None, pattern="^(bot|task|agent)$")
    description: str | None = Field(None, max_length=500)
    owner_user_id: int | None = Field(None, ge=1)
    status: str | None = Field(None, pattern="^(active|disabled)$")
    expires_at: datetime | None = None


class DelegationCreateRequest(BaseModel):
    service_account_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)
    target_type: str = Field("toolset", pattern="^(server|toolset)$")
    target_id: int = Field(..., ge=1)
    expires_at: datetime | None = None
    granted_via: str = Field("manual", max_length=32)
    reason: str | None = Field(None, max_length=500)


@router.get("", summary="服务账号列表")
async def list_service_accounts(
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("mcp:read")),
):
    accounts = await service_account_service.list_service_accounts(session)
    return {
        "code": 200,
        "data": {"items": [service_account_service.serialize(a) for a in accounts]},
    }


@router.post("", summary="创建服务账号（令牌只返回一次）")
async def create_service_account(
    req: ServiceAccountCreateRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:update")),
):
    sa, token = await service_account_service.create_service_account(
        session,
        name=req.name,
        kind=req.kind,
        description=req.description,
        owner_user_id=req.owner_user_id,
        expires_at=req.expires_at,
        created_by=current_user["id"],
    )
    await session.commit()
    return {
        "code": 200,
        "message": "服务账号已创建，请立即保存令牌（之后无法再次查看）",
        "data": {"account": service_account_service.serialize(sa), "token": token},
    }


@router.patch("/{sa_id}", summary="更新服务账号")
async def update_service_account(
    sa_id: int,
    req: ServiceAccountUpdateRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("mcp:update")),
):
    sa = await service_account_service.update_service_account(
        session, sa_id, **req.model_dump(exclude_unset=True)
    )
    await session.commit()
    return {"code": 200, "data": {"account": service_account_service.serialize(sa)}}


@router.post("/{sa_id}/rotate-token", summary="轮换令牌（旧令牌立即失效）")
async def rotate_token(
    sa_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("mcp:update")),
):
    sa, token = await service_account_service.rotate_token(session, sa_id)
    await session.commit()
    return {
        "code": 200,
        "message": "令牌已轮换，旧令牌立即失效",
        "data": {"account": service_account_service.serialize(sa), "token": token},
    }


@router.delete("/{sa_id}", summary="删除服务账号（连带删除其委托）")
async def delete_service_account(
    sa_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("mcp:update")),
):
    await service_account_service.delete_service_account(session, sa_id)
    await session.commit()
    return {"code": 200, "message": "服务账号已删除", "data": None}


# ─── 委托授权 ────────────────────────────────────────────────────────────────

delegation_router = APIRouter(prefix="/delegation-grants", tags=["机器身份"])


@delegation_router.get("", summary="委托授权列表")
async def list_delegations(
    service_account_id: int | None = None,
    user_id: int | None = None,
    include_revoked: bool = False,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("mcp:read")),
):
    grants = await service_account_service.list_delegations(
        session,
        service_account_id=service_account_id,
        user_id=user_id,
        include_revoked=include_revoked,
    )
    return {
        "code": 200,
        "data": {
            "items": [service_account_service.serialize_delegation(g) for g in grants]
        },
    }


@delegation_router.post("", summary="新增委托授权")
async def create_delegation(
    req: DelegationCreateRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:update")),
):
    grant = await service_account_service.grant_delegation(
        session,
        service_account_id=req.service_account_id,
        user_id=req.user_id,
        target_type=req.target_type,
        target_id=req.target_id,
        expires_at=req.expires_at,
        granted_via=req.granted_via,
        granted_by=current_user["id"],
        reason=req.reason,
    )
    await mcp_authz_repo.bump_policy_version(
        session,
        current_user["id"],
        f"新增委托 sa:{req.service_account_id} -> user:{req.user_id} "
        f"{req.target_type}:{req.target_id}",
    )
    await session.commit()
    return {
        "code": 200,
        "data": {"grant": service_account_service.serialize_delegation(grant)},
    }


@delegation_router.delete("/{grant_id}", summary="撤销委托授权（下一次调用即拒）")
async def revoke_delegation(
    grant_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:update")),
):
    grant = await service_account_service.revoke_delegation(
        session, grant_id, revoked_by=current_user["id"]
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="委托记录不存在")
    await mcp_authz_repo.bump_policy_version(
        session,
        current_user["id"],
        f"撤销委托 sa:{grant.service_account_id} -> user:{grant.user_id} "
        f"{grant.target_type}:{grant.target_id}",
    )
    await session.commit()
    return {
        "code": 200,
        "data": {"grant": service_account_service.serialize_delegation(grant)},
    }
