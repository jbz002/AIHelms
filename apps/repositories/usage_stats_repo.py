"""使用统计 repository。聚合 text() SQL，只读平台已落库日志（红线：禁直读 LiteLLM）。

MCP：user_id 哨兵 0 用 NULLIF 排除；cost 两列求和。
Skill：无 cost 列、无哨兵 0；动作仅 download / agent_download。
"""

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def mcp_totals(session: AsyncSession, server_id: int, start: date) -> dict:
    sql = text(
        "SELECT "
        "COUNT(*) AS total_calls, "
        "COUNT(DISTINCT NULLIF(user_id, 0)) AS unique_users, "
        "COALESCE(SUM(internal_cost + external_cost), 0)::numeric(12,6) AS total_cost, "
        "COALESCE(AVG(duration_ms), 0)::int AS avg_duration_ms "
        "FROM aihelms.mcp_call_logs "
        "WHERE server_id = :sid AND called_at >= :start"
    )
    row = (await session.execute(sql, {"sid": server_id, "start": start})).one()
    return {
        "total_calls": int(row.total_calls or 0),
        "unique_users": int(row.unique_users or 0),
        "total_cost": round(float(row.total_cost or 0), 6),
        "avg_duration_ms": int(row.avg_duration_ms or 0),
    }


async def mcp_trend(
    session: AsyncSession, server_id: int, start: date
) -> list[tuple[date, int]]:
    sql = text(
        "SELECT date_trunc('day', called_at)::date AS d, COUNT(*) AS cnt "
        "FROM aihelms.mcp_call_logs "
        "WHERE server_id = :sid AND called_at >= :start "
        "GROUP BY 1 ORDER BY 1"
    )
    result = await session.execute(sql, {"sid": server_id, "start": start})
    return [(row.d, int(row.cnt)) for row in result.fetchall()]


async def mcp_tool_distribution(
    session: AsyncSession, server_id: int, start: date, limit: int = 10
) -> list[tuple[str, int]]:
    sql = text(
        "SELECT namespaced_tool_name AS tool_name, COUNT(*) AS cnt "
        "FROM aihelms.mcp_call_logs "
        "WHERE server_id = :sid AND called_at >= :start "
        "GROUP BY 1 ORDER BY cnt DESC LIMIT :limit"
    )
    result = await session.execute(
        sql, {"sid": server_id, "start": start, "limit": limit}
    )
    return [(row.tool_name, int(row.cnt)) for row in result.fetchall()]


async def skill_totals(session: AsyncSession, skill_id: int, start: date) -> dict:
    sql = text(
        "SELECT "
        "COUNT(*) AS total_downloads, "
        "COUNT(DISTINCT user_id) AS unique_users, "
        "COUNT(*) FILTER (WHERE action = 'agent_download') AS agent_downloads, "
        "COUNT(*) FILTER (WHERE action = 'download') AS manual_downloads "
        "FROM aihelms.skill_usage_logs "
        "WHERE skill_id = :sid AND created_at >= :start"
    )
    row = (await session.execute(sql, {"sid": skill_id, "start": start})).one()
    return {
        "total_downloads": int(row.total_downloads or 0),
        "unique_users": int(row.unique_users or 0),
        "agent_downloads": int(row.agent_downloads or 0),
        "manual_downloads": int(row.manual_downloads or 0),
    }


async def skill_trend(
    session: AsyncSession, skill_id: int, start: date
) -> list[tuple[date, int]]:
    sql = text(
        "SELECT date_trunc('day', created_at)::date AS d, COUNT(*) AS cnt "
        "FROM aihelms.skill_usage_logs "
        "WHERE skill_id = :sid AND created_at >= :start "
        "GROUP BY 1 ORDER BY 1"
    )
    result = await session.execute(sql, {"sid": skill_id, "start": start})
    return [(row.d, int(row.cnt)) for row in result.fetchall()]


async def skill_action_distribution(
    session: AsyncSession, skill_id: int, start: date
) -> list[tuple[str, int]]:
    sql = text(
        "SELECT action, COUNT(*) AS cnt "
        "FROM aihelms.skill_usage_logs "
        "WHERE skill_id = :sid AND created_at >= :start "
        "GROUP BY 1 ORDER BY cnt DESC"
    )
    result = await session.execute(sql, {"sid": skill_id, "start": start})
    return [(row.action, int(row.cnt)) for row in result.fetchall()]
