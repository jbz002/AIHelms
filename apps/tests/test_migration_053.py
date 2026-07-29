"""迁移 053 校验：skill:contribute 权限 + contributor 角色(is_system=false) + 绑定关系存在。

init.sql（fresh install）与 053 迁移（升级）双写，运行 ./dev/migrate 后均应落库。
"""

import pytest
from sqlalchemy import select

from core.database import get_worker_session_factory
from models.db import Permission, Role, RolePermission


def _session():
    return get_worker_session_factory()()


@pytest.mark.asyncio
async def test_skill_contribute_permission_seeded():
    async with _session() as s:
        perm = await s.execute(
            select(Permission).where(Permission.code == "skill:contribute")
        )
        perm = perm.scalar_one_or_none()
        assert perm is not None
        assert perm.resource == "skill"
        assert perm.action == "contribute"


@pytest.mark.asyncio
async def test_contributor_role_seeded_non_system():
    async with _session() as s:
        role = await s.execute(select(Role).where(Role.name == "contributor"))
        role = role.scalar_one_or_none()
        assert role is not None
        assert role.is_system is False


@pytest.mark.asyncio
async def test_contributor_bound_to_skill_contribute():
    async with _session() as s:
        linked = await s.execute(
            select(RolePermission)
            .join(Role, RolePermission.role_id == Role.id)
            .join(Permission, RolePermission.permission_id == Permission.id)
            .where(Role.name == "contributor", Permission.code == "skill:contribute")
        )
        assert linked.scalar_one_or_none() is not None
