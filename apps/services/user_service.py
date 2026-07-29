import logging

from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_password_hash
from exceptions import ConflictError, NotFoundError
from models.db import User
from repositories import user_repo
from services import ai_key_service, litellm_client

logger = logging.getLogger(__name__)


async def list_users(
    session: AsyncSession, page: int = 1, page_size: int = 20, keyword: str = ""
) -> dict:
    total = await user_repo.count_users(session, keyword)
    users = await user_repo.find_users(session, page, page_size, keyword)
    items = [_serialize_user(u) for u in users]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def get_user_by_id(session: AsyncSession, user_id: int) -> dict:
    user = await user_repo.find_user_by_id(session, user_id)
    if not user:
        raise NotFoundError("user", user_id)
    return _serialize_user_detail(user)


async def provision_user_resources(session: AsyncSession, user: User) -> None:
    """建 litellm 账号 + 个人主 key。幂等，每步独立 commit 保证重试安全。

    普通建用户与 SSO 首登共用：litellm_user_id 未设则建 litellm 账号并立刻落库，
    再建个人主 key（create_personal_main_key 自身幂等）。任一步失败，下次调用补建。
    """
    if not user.litellm_user_id:
        litellm_user_id = f"aihelms_user_{user.id}"
        await litellm_client.create_user(litellm_user_id, user.email)
        user.litellm_user_id = litellm_user_id
        await session.commit()
    await ai_key_service.create_personal_main_key(session, user.id, user.username)
    await session.commit()


async def create_user(
    session: AsyncSession,
    username: str,
    email: str,
    password: str,
    phone: str = "",
    display_name: str = "",
    position: str = "",
    avatar: str = "",
    is_active: bool = True,
) -> dict:
    existing = await user_repo.find_user_by_username_or_email(session, username, email)
    if existing:
        raise ConflictError("用户名或邮箱已存在")

    hashed = get_password_hash(password)
    user = User(
        username=username,
        email=email,
        hashed_password=hashed,
        phone=phone,
        display_name=display_name,
        position=position,
        avatar=avatar,
        is_active=is_active,
    )
    user = await user_repo.create_user(session, user)

    await provision_user_resources(session, user)
    return _serialize_user(user)


async def update_user(
    session: AsyncSession,
    user_id: int,
    email: str | None = None,
    phone: str | None = None,
    display_name: str | None = None,
    position: str | None = None,
    avatar: str | None = None,
    is_active: bool | None = None,
) -> dict:
    user = await user_repo.find_user_by_id(session, user_id)
    if not user:
        raise NotFoundError("user", user_id)

    if email is not None:
        dup = await user_repo.find_user_by_email_exclude(session, email, user_id)
        if dup:
            raise ConflictError("邮箱已被使用")
        user.email = email

    if phone is not None:
        user.phone = phone
    if display_name is not None:
        user.display_name = display_name
    if position is not None:
        user.position = position
    if avatar is not None:
        user.avatar = avatar
    active_changed = False
    if is_active is not None and is_active != user.is_active:
        user.is_active = is_active
        active_changed = True

    # 用户启用/禁用时，同步名下所有 AI Key 到 LiteLLM（禁用=卡住预算，启用=恢复）
    if active_changed:
        await ai_key_service.sync_user_keys_active(session, user_id, is_active)

    await session.commit()
    await session.refresh(user)
    return _serialize_user_detail(user)


async def delete_user(session: AsyncSession, user_id: int) -> None:
    user = await user_repo.find_user_by_id(session, user_id)
    if not user:
        raise NotFoundError("user", user_id)
    if user.is_admin:
        raise ConflictError("不能删除管理员账户")

    # 检查用户是否创建了不可转移的资源（RESTRICT FK）
    from sqlalchemy import func, select

    from models.db import Agent, AiKey, ApiKey, McpServer, Skill

    resource_checks = [
        (ApiKey, "API Key"),
        (AiKey, "AI Key"),
        (McpServer, "MCP Server"),
        (Skill, "Skill"),
        (Agent, "Agent"),
    ]
    for model, label in resource_checks:
        count = await session.scalar(
            select(func.count()).select_from(model).where(model.created_by == user_id)
        )
        if count:
            raise ConflictError(f"该用户创建了 {label}，请先转移资源所有权后再删除")

    # 硬删除前，先禁用名下所有 AI Key（LiteLLM 侧预算置 0）
    await ai_key_service.sync_user_keys_active(session, user_id, False)
    await session.delete(user)
    await session.commit()


async def reset_password(
    session: AsyncSession, user_id: int, new_password: str
) -> None:
    user = await user_repo.find_user_by_id(session, user_id)
    if not user:
        raise NotFoundError("user", user_id)
    user.hashed_password = get_password_hash(new_password)
    await session.commit()


async def update_user_roles(
    session: AsyncSession, user_id: int, role_ids: list[int]
) -> None:
    user = await user_repo.find_user_by_id(session, user_id)
    if not user:
        raise NotFoundError("user", user_id)

    # super_admin 角色不可通过后台分配
    from sqlalchemy import select

    from models.db import Role

    if role_ids:
        result = await session.execute(select(Role).where(Role.id.in_(role_ids)))
        roles = list(result.scalars().all())
        assigned_role_names = {r.name for r in roles}
        if "super_admin" in assigned_role_names:
            raise ConflictError("super_admin 角色不可手动分配")
        user.is_admin = "admin" in assigned_role_names
    else:
        user.is_admin = False

    await user_repo.replace_user_roles(session, user_id, role_ids)
    await session.commit()


async def update_user_departments(
    session: AsyncSession, user_id: int, department_ids: list[int]
) -> None:
    user = await user_repo.find_user_by_id(session, user_id)
    if not user:
        raise NotFoundError("user", user_id)
    await user_repo.replace_user_departments(session, user_id, department_ids)
    await session.commit()


async def update_user_projects(
    session: AsyncSession, user_id: int, project_ids: list[int]
) -> None:
    user = await user_repo.find_user_by_id(session, user_id)
    if not user:
        raise NotFoundError("user", user_id)
    await user_repo.replace_user_projects(session, user_id, project_ids)
    await session.commit()


def _serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "display_name": user.display_name,
        "position": user.position,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "roles": [
            {
                "id": ur.role.id,
                "name": ur.role.name,
                "display_name": ur.role.display_name,
            }
            for ur in user.roles
        ],
        "departments": [
            {
                "id": ud.department.id,
                "name": ud.department.name,
                "is_manager": ud.is_manager,
            }
            for ud in user.departments
        ],
        "projects": [
            {"id": up.project.id, "name": up.project.name} for up in user.projects
        ],
    }


def _serialize_user_detail(user: User) -> dict:
    data = _serialize_user(user)
    data["avatar"] = user.avatar
    data["litellm_user_id"] = user.litellm_user_id
    data["updated_at"] = user.updated_at.isoformat() if user.updated_at else None
    return data
