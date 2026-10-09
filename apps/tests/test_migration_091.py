"""迁移 091 校验：撤回单名称契约——uq_skills_name 移除、idx_skills_name 恢复、
090 收敛掉的存量中文名恢复。

迁移启动时自动跑（或 ./dev/migrate），此处断言终态；幂等重跑应保持终态不变。
"""

from pathlib import Path

import pytest
from sqlalchemy import text

from core.database import get_worker_session_factory

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _session():
    return get_worker_session_factory()()


@pytest.mark.asyncio
async def test_unique_index_dropped_plain_index_restored():
    async with _session() as s:
        rows = await s.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='aihelms' AND tablename='skills' AND indexdef LIKE '%(name)%'"
            )
        )
        indexes = {r[0]: r[1] for r in rows}
        assert "uq_skills_name" not in indexes, indexes
        assert "idx_skills_name" in indexes, indexes
        assert "UNIQUE" not in indexes["idx_skills_name"]


@pytest.mark.asyncio
async def test_converged_names_reverted():
    """090 曾把 3 个存量中文名改成 frontmatter kebab 名；091 恢复原名。

    dev 库若没跑过 090（无 kebab 名），UPDATE miss no-op，本用例对两种
    状态都成立：不存在的 kebab 名不得残留。
    """
    async with _session() as s:
        rows = await s.execute(
            text(
                "SELECT name FROM aihelms.skills WHERE name IN "
                "('docs-crawl-scout', 'skill-maintenance', 'aihub-integration')"
            )
        )
        assert rows.fetchall() == []


@pytest.mark.asyncio
async def test_migration_idempotent():
    """重跑 091 SQL 本体，终态不变（走原生 asyncpg 多语句，同 migrate.py）。"""
    import asyncpg

    from core.config import settings
    from core.migrate import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "091_revert_skill_name_unique.sql").read_text("utf-8")
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()
    await test_unique_index_dropped_plain_index_restored()
    await test_converged_names_reverted()


def test_migration_and_init_ddl_consistent():
    migration = (
        REPO_ROOT / "docker" / "db" / "migrations" / "091_revert_skill_name_unique.sql"
    ).read_text(encoding="utf-8")
    init_sql = (REPO_ROOT / "docker" / "db" / "init.sql").read_text(encoding="utf-8")
    assert "DROP INDEX IF EXISTS aihelms.uq_skills_name" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_skills_name" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_skills_name" in init_sql
    assert (
        "uq_skills_name" not in init_sql
    ), "init.sql 不应再建唯一索引"
