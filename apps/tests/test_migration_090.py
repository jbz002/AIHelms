"""迁移 090 校验：skills.name 单名称收敛 + 全局唯一索引。

迁移启动时自动跑（或 ./dev/migrate），此处断言终态：
- uq_skills_name 唯一索引存在、旧普通索引 idx_skills_name 已移除
- 全表 name 无重复（唯一索引的必然推论，防有人手动 DROP 后写入脏数据）
- init.sql 与迁移文件双写同形（新装库直达终态）
"""

from pathlib import Path

import pytest
from sqlalchemy import text

from core.database import get_worker_session_factory

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _session():
    return get_worker_session_factory()()


@pytest.mark.asyncio
async def test_uq_skills_name_index_exists():
    async with _session() as s:
        result = await s.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'aihelms' AND tablename = 'skills'"
            )
        )
        rows = {r[0]: r[1] for r in result.all()}
    assert "uq_skills_name" in rows, f"唯一索引缺失，现有: {sorted(rows)}"
    assert "UNIQUE" in rows["uq_skills_name"].upper()
    assert "idx_skills_name" not in rows, "旧普通索引应已被 090 移除"


@pytest.mark.asyncio
async def test_no_duplicate_names():
    async with _session() as s:
        result = await s.execute(
            text(
                "SELECT name, count(*) FROM aihelms.skills "
                "GROUP BY name HAVING count(*) > 1"
            )
        )
        dupes = result.all()
    assert dupes == [], f"name 仍有重复: {dupes}"


def test_migration_and_init_ddl_consistent():
    migration = (
        REPO_ROOT / "docker" / "db" / "migrations" / "090_skill_name_unify_unique.sql"
    ).read_text(encoding="utf-8")
    init_sql = (REPO_ROOT / "docker" / "db" / "init.sql").read_text(encoding="utf-8")
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_name" in migration
    assert "DROP INDEX IF EXISTS aihelms.idx_skills_name" in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_name" in init_sql
    assert (
        "CREATE INDEX IF NOT EXISTS idx_skills_name" not in init_sql
    ), "init.sql 不应再建旧普通索引"
