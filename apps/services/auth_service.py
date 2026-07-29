import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import create_access_token
from exceptions import NotFoundError, UnauthorizedError
from models.db import Permission, RolePermission, User, UserRole
from repositories import user_repo

logger = logging.getLogger(__name__)


async def oauth2_login(session: AsyncSession, code: str) -> tuple[str, User]:
    """OAuth2 授权码换 AI Hub 用户，upsert 本地档案，签本地 JWT。"""
    if not settings.ai_hub_url:
        raise RuntimeError("AI Hub 未配置(ai_hub_url 为空)")

    base = settings.ai_hub_url.rstrip("/")
    async with httpx.AsyncClient(timeout=10) as client:
        # 1. code → token + 基础 user（无 app_roles）
        resp = await client.post(f"{base}/api/v1/auth/token", json={"code": code})
        if resp.status_code != 200:
            logger.warning(
                "aihub token exchange failed: status=%s body=%s",
                resp.status_code,
                resp.text,
            )
            raise UnauthorizedError("授权码无效或已过期")
        data = resp.json()
        aihub_token = data["access_token"]
        aihub_user = data["user"]

        # 2. 补 app_roles + phone（/token user 无 phone，/me 才有）
        app_roles: list[str] = []
        phone: str = ""
        me = await client.get(
            f"{base}/api/v1/auth/me",
            params={"app_code": settings.ai_hub_app_code},
            headers={"Authorization": f"Bearer {aihub_token}"},
        )
        if me.status_code == 200:
            me_data = me.json()
            app_roles = list(me_data.get("app_roles") or [])
            phone = me_data.get("phone") or ""

    # 3. upsert 本地用户
    aihub_user_id = str(aihub_user["id"])
    email = aihub_user.get("email") or f"{aihub_user_id}@aihub.local"
    username = aihub_user.get("username") or f"aihub_{aihub_user_id[:8]}"
    user = await user_repo.upsert_user_from_aihub(
        session,
        aihub_user_id=aihub_user_id,
        username=username,
        email=email,
        display_name=aihub_user.get("real_name") or "",
        aihub_department_id=(
            str(aihub_user["department_id"])
            if aihub_user.get("department_id")
            else None
        ),
        phone=phone,
    )

    # 4. 签本地 JWT（is_admin 由 app_roles 映射，permissions 仍走本地 RBAC）
    permissions = await get_user_permissions(session, user.id)
    is_admin = settings.ai_hub_admin_role in app_roles
    token_data = {
        "sub": str(user.id),
        "username": user.username,
        "is_admin": is_admin,
        "permissions": permissions,
        "aihub_user_id": aihub_user_id,
        "app_roles": app_roles,
    }
    token = create_access_token(token_data)
    # get_db 依赖不自动 commit，SSO upsert 必须显式落库（否则请求结束回滚，用户档案丢失）
    await session.commit()
    return token, user


async def get_user_permissions(session: AsyncSession, user_id: int) -> list[str]:
    result = await session.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
        .distinct()
    )
    return list(result.scalars().all())


async def get_current_user_info(session: AsyncSession, user_id: int) -> dict:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("user", user_id)
    permissions = await get_user_permissions(session, user_id)
    departments = [
        {"id": ud.department.id, "name": ud.department.name}
        for ud in user.departments
        if ud.department
    ]
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "display_name": user.display_name,
        "avatar": user.avatar,
        "position": user.position,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "permissions": permissions,
        "roles": [
            {
                "id": ur.role.id,
                "name": ur.role.name,
                "display_name": ur.role.display_name,
            }
            for ur in user.roles
        ],
        "departments": departments,
    }
