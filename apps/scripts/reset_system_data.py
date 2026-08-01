"""一键重置平台系统数据(本地 dev 用)。

保留不动:
  - 模型纳管(供应商/模型)、API文档、MCP、Skill 四个业务模块
  - seed 字典 / 单例 / RBAC 基线(roles/permissions/role_permissions/business_scenarios 等)

清空回初始状态:
  - 用户(仅留最早一个 is_admin/is_super_admin 管理员)、组织、AI 身份、日志、成本、
    申请、智能体、自定义实体、audit、可见性桥接表
  - 由平台同步到 LiteLLM 的 virtual keys 与 project teams(departments 无 LiteLLM team,跳过)

清空策略:
  - users / ai_policies_audits 被 KEEP 表 FK 引用,用 DELETE 触发 SET NULL,避免 TRUNCATE CASCADE
    误伤 KEEP 表(skills/mcp/documents.created_by → users;skills/mcp.latest_ai_policies_audit_id → audits)
  - 其余 RESET 表组内一次性 TRUNCATE RESTART IDENTITY(组内互引用,无 KEEP 引用为父,不需 CASCADE)
  - 清空 user_roles 后给保留的 admin 重新绑定 super_admin 角色(roles/role_permissions 是 KEEP seed)

运行:
  cd apps && uv run python -m scripts.reset_system_data                  # dry-run 预览(默认)
  cd apps && uv run python -m scripts.reset_system_data --yes             # 真执行
  cd apps && uv run python -m scripts.reset_system_data --yes --no-litellm  # 跳过 LiteLLM 清理
"""

import argparse
import asyncio

from sqlalchemy import text

from core.database import async_session
from services import litellm_client
from services.litellm_client import LiteLLMError

# TRUNCATE 清空的表(组内一次性,RESTART IDENTITY)。
# 不含 users / ai_policies_audits —— 被 KEEP 表 FK 引用,改用 DELETE。
RESET_TRUNCATE_TABLES = [
    "user_roles", "user_departments", "user_projects",
    "model_user_visibility", "model_department_visibility",
    "ai_keys", "ai_key_model_limits", "key_scenarios",
    "departments", "projects", "api_keys",
    "usage_logs", "llm_call_logs", "mcp_call_logs",
    "skill_usage_logs", "agent_usage_logs",
    "cost_summary_daily", "efficiency_reports", "efficiency_suggestions",
    "admin_audit_logs", "idempotency_records",
    "storage_deletion_compensations", "export_tasks",
    "resource_applications", "publish_reviews",
    "agents", "agent_categories", "agent_platforms",
    "custom_entity_types", "custom_entities",
    "sync_state",
]

# 验证用:RESET 前后行数应不变的 KEEP 表。
KEEP_REPORT_TABLES = [
    "providers", "models", "model_deployments", "credentials",
    "mcp_servers", "mcp_tools", "mcp_server_versions",
    "skills", "skill_versions",
    "documents", "document_libraries",
    "roles", "permissions", "role_permissions",
    "business_scenarios",
]

ADMIN_ROLE_NAME = "super_admin"

# 查所有引用 aihelms.users.id 的 (表, 列),用于 DELETE users 前断开引用。
# 部分 created_by FK 是 NO ACTION(如 ai_keys/skills/mcp_servers),DELETE users 会被阻塞,
# 故先 UPDATE 这些列为 NULL。表名/列名来自系统目录,可信,非用户输入。
REFS_SQL = """
SELECT c.relname AS t, a.attname AS col
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(k.conkey)
JOIN pg_class rc ON rc.oid = k.confrelid
JOIN pg_attribute ra ON ra.attrelid = rc.oid AND ra.attnum = ANY(k.confkey)
WHERE n.nspname = 'aihelms' AND rc.relname = 'users' AND ra.attname = 'id'
  AND k.contype = 'f'
"""


async def pick_admin_id(session) -> int | None:
    sql = text(
        "SELECT id FROM aihelms.users "
        "WHERE is_admin = true OR is_super_admin = true "
        "ORDER BY id ASC LIMIT 1"
    )
    return (await session.execute(sql)).scalar_one_or_none()


async def collect_litellm_targets(session) -> tuple[list[str], list[str]]:
    keys = list(
        (
            await session.execute(
                text(
                    "SELECT litellm_key_id FROM aihelms.ai_keys "
                    "WHERE litellm_key_id IS NOT NULL"
                )
            )
        ).scalars().all()
    )
    teams = list(
        (
            await session.execute(
                text(
                    "SELECT litellm_team_id FROM aihelms.projects "
                    "WHERE litellm_team_id IS NOT NULL"
                )
            )
        ).scalars().all()
    )
    return keys, teams


async def collect_counts(session, tables: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in tables:
        counts[t] = (
            await session.execute(text(f"SELECT count(*) FROM aihelms.{t}"))
        ).scalar_one()
    return counts


async def purge_litellm(key_ids: list[str], team_ids: list[str]) -> None:
    print(f"== 清理 LiteLLM:{len(key_ids)} 个 key,{len(team_ids)} 个 project team ==")
    for kid in key_ids:
        try:
            await litellm_client.delete_key(kid)
            print(f"  key {kid[:16]}... deleted")
        except LiteLLMError as e:
            print(f"  key {kid[:16]}... WARN: {e}")
    for tid in team_ids:
        try:
            await litellm_client.delete_team(tid)
            print(f"  team {tid} deleted")
        except LiteLLMError as e:
            print(f"  team {tid} WARN: {e}")


async def reset_db(admin_id: int) -> None:
    print("== 清空平台 DB(单事务) ==")
    truncate_list = ", ".join(f"aihelms.{t}" for t in RESET_TRUNCATE_TABLES)
    async with async_session() as session:
        async with session.begin():
            # 1. 其余 RESET 表组内 TRUNCATE,重置序列(含 ai_keys,先清 NO ACTION 子表)
            await session.execute(text(f"TRUNCATE {truncate_list} RESTART IDENTITY"))
            # 1b. 清 LiteLLM spend 源头(LiteLLM 与平台共用同一 PG,spend 在 public."LiteLLM_SpendLogs"),
            #     否则 llm_log sync/reconcile 定时任务会把 LiteLLM 残留 spend 回灌 aihelms.llm_call_logs。
            await session.execute(text('TRUNCATE public."LiteLLM_SpendLogs"'))
            # 2. 被 KEEP 表 FK 引用的 ai_policies_audits:DELETE 触发 SET NULL
            await session.execute(text("DELETE FROM aihelms.ai_policies_audits"))
            # 3. 断开所有引用 users.id 的列(含 NO ACTION 的 KEEP 表 created_by,如 skills/mcp_servers)。
            #    NOT NULL 列(如 skill_review_tasks.submitted_by)不能置 NULL → 改指 admin(接管)。
            #    nullable 列也统一改指 admin,语义为被删用户的创建/提交归属由 admin 接管。
            refs = (await session.execute(text(REFS_SQL))).all()
            for row in refs:
                tname, col = row[0], row[1]
                await session.execute(
                    text(
                        f"UPDATE aihelms.{tname} SET {col} = :aid "
                        f"WHERE {col} IS NOT NULL AND {col} != :aid"
                    ),
                    {"aid": admin_id},
                )
            # 4. 删非管理员用户
            await session.execute(
                text("DELETE FROM aihelms.users WHERE id != :aid"),
                {"aid": admin_id},
            )
            # 5. re-seed sync_state 增量游标(对齐 init.sql 初始值)
            await session.execute(
                text(
                    "INSERT INTO aihelms.sync_state (key, last_sync_at) VALUES "
                    "('llm_logs', NOW() - INTERVAL '1 hour'), "
                    "('mcp_logs', NOW() - INTERVAL '1 hour')"
                )
            )
            # 6. 给保留 admin 重绑 super_admin 角色(roles/role_permissions 是 KEEP seed 未动)
            await session.execute(
                text(
                    "INSERT INTO aihelms.user_roles (user_id, role_id) "
                    "SELECT :aid, id FROM aihelms.roles WHERE name = :role"
                ),
                {"aid": admin_id, "role": ADMIN_ROLE_NAME},
            )
    print("  平台 DB 已重置")


def print_plan(admin_id: int, users_total: int, key_ids, team_ids, keep_before, no_litellm: bool) -> None:
    print(f"保留管理员: user_id={admin_id}"
          f"(当前 {users_total} 个用户,将删 {users_total - 1} 个)")
    litellm_note = "(将跳过)" if no_litellm else ""
    print(f"待删 LiteLLM: {len(key_ids)} key / {len(team_ids)} team {litellm_note}")
    print(f"将 DELETE: ai_policies_audits、非管理员 users")
    print(f"将 UPDATE: 所有引用 users 的列(created_by/submitted_by 等)改指 admin,断开 NO ACTION FK")
    print(f"将 TRUNCATE {len(RESET_TRUNCATE_TABLES)} 张表 RESTART IDENTITY")
    print(f"将 re-seed sync_state 游标,给 admin 绑 {ADMIN_ROLE_NAME} 角色")
    print("KEEP 表当前行数(重置后应不变):")
    for t, c in keep_before.items():
        print(f"  {t}: {c}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="重置平台系统数据(本地 dev)")
    parser.add_argument("--yes", action="store_true", help="真执行(默认 dry-run 预览)")
    parser.add_argument("--no-litellm", action="store_true", help="跳过 LiteLLM 清理")
    args = parser.parse_args()

    async with async_session() as session:
        admin_id = await pick_admin_id(session)
        if admin_id is None:
            print("ERROR: 无 is_admin/is_super_admin 用户,无法保留管理员。退出。")
            return
        key_ids, team_ids = await collect_litellm_targets(session)
        keep_before = await collect_counts(session, KEEP_REPORT_TABLES)
        users_total = (
            await session.execute(text("SELECT count(*) FROM aihelms.users"))
        ).scalar_one()

    print_plan(admin_id, users_total, key_ids, team_ids, keep_before, args.no_litellm)

    if not args.yes:
        print("\n[dry-run] 未改动任何数据。加 --yes 真执行。")
        return

    if not args.no_litellm:
        await purge_litellm(key_ids, team_ids)
    await reset_db(admin_id)

    async with async_session() as session:
        keep_after = await collect_counts(session, KEEP_REPORT_TABLES)
        users_after = (
            await session.execute(text("SELECT count(*) FROM aihelms.users"))
        ).scalar_one()
        reset_counts = await collect_counts(
            session, ["ai_keys", "departments", "projects", "agents", "resource_applications"]
        )

    print("\n== 验证 ==")
    print(f"users 剩余: {users_after}(预期 1)")
    print("RESET 抽查(预期 0):")
    for t, c in reset_counts.items():
        print(f"  {t}: {c}")
    drift = [t for t in KEEP_REPORT_TABLES if keep_after[t] != keep_before[t]]
    if drift:
        print(f"WARN: KEEP 表行数变化: {drift}")
    else:
        print("KEEP 表行数全部不变 OK")
    print("\n重置完成。")


if __name__ == "__main__":
    asyncio.run(main())
