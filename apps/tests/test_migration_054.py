"""迁移 054 校验：mcp:contribute / agent:contribute 权限 + contributor 角色绑定二者。

init.sql（fresh install）与 054 迁移（升级）双写，运行 ./dev/migrate 后均应落库。
"""

import pytest
from sqlalchemy import select

from core.database import get_worker_session_factory
from models.db import Permission, Role, RolePermission


def _session():
    return get_worker_session_factory()()


@pytest.mark.parametrize(
    "code,resource", [("mcp:contribute", "mcp"), ("agent:contribute", "agent")]
)
@pytest.mark.asyncio
async def test_contribute_permissions_seeded(code: str, resource: str):
    async with _session() as s:
        perm = await s.execute(select(Permission).where(Permission.code == code))
        perm = perm.scalar_one_or_none()
        assert perm is not None
        assert perm.resource == resource
        assert perm.action == "contribute"


@pytest.mark.parametrize("code", ["mcp:contribute", "agent:contribute"])
@pytest.mark.asyncio
async def test_contributor_bound_to_contribute_permissions(code: str):
    async with _session() as s:
        linked = await s.execute(
            select(RolePermission)
            .join(Role, RolePermission.role_id == Role.id)
            .join(Permission, RolePermission.permission_id == Permission.id)
            .where(Role.name == "contributor", Permission.code == code)
        )
        assert linked.scalar_one_or_none() is not None
