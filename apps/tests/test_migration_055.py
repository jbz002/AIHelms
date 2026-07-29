"""迁移 055 校验：mcp_servers / agents 的 created_by 索引存在。

contributor 工作台按创建者列表/计数查询依赖此索引；init.sql（fresh）与 055（升级）双写。
"""

import pytest
from sqlalchemy import text

from core.database import get_worker_session_factory


def _session():
    return get_worker_session_factory()()


@pytest.mark.parametrize(
    "index_name",
    ["idx_mcp_servers_created_by", "idx_agents_created_by"],
)
@pytest.mark.asyncio
async def test_creator_indexes_exist(index_name: str):
    async with _session() as s:
        exists = await s.execute(
            text(
                "SELECT 1 FROM pg_indexes "
                "WHERE schemaname = 'aihelms' AND indexname = :n"
            ),
            {"n": index_name},
        )
        assert exists.scalar_one() == 1
