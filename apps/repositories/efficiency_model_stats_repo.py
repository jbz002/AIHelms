"""用户×模型用量统计仓库层（cc-switch 口径）。

汇总指标来自 cost_summary_daily；速度/首字来自 llm_call_logs 明细。
"""

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.efficiency_cost_repo import _build_cost_filters

# 平台模型匹配 join：与 get_cost_detail_by_model 同一套别名映射
_PLATFORM_MODEL_JOIN = (
    " LEFT JOIN LATERAL ("
    "   SELECT d.id AS deployment_id, d.model_id"
    "   FROM aihelms.model_deployments d"
    "   LEFT JOIN aihelms.models dm ON dm.id = d.model_id"
    "   WHERE d.credential_id = c.provider_id"
    "     AND (d.litellm_params->>'model' = c.model"
    "       OR d.litellm_model_id = c.model"
    "       OR d.deploy_name = c.model"
    "       OR dm.model_id = c.model"
    "       OR split_part(c.model, '/', 2) = dm.model_id"
    "       OR dm.name = c.model)"
    "   ORDER BY d.is_active DESC, d.id DESC"
    "   LIMIT 1"
    " ) md ON TRUE"
    " LEFT JOIN aihelms.models m ON m.id = md.model_id"
)


async def get_user_model_summary(
    session: AsyncSession, start_date: date, end_date: date, user_id: int
) -> list[dict]:
    sql = text(
        "SELECT c.model,"
        " COALESCE(m.name, c.model) AS platform_model_name,"
        " COALESCE(m.model_id, split_part(c.model, '/', 2), c.model) AS platform_model_id,"
        " COALESCE(SUM(c.total_requests), 0),"
        " COALESCE(SUM(c.successful_requests), 0),"
        " COALESCE(SUM(c.input_tokens), 0),"
        " COALESCE(SUM(c.output_tokens), 0),"
        " COALESCE(SUM(c.cache_read_tokens), 0),"
        " COALESCE(SUM(c.cache_creation_tokens), 0),"
        " COALESCE(SUM(GREATEST(c.input_tokens - c.cache_read_tokens, 0)), 0) AS fresh_input_tokens,"
        " COALESCE(SUM(c.internal_cost), 0),"
        " COALESCE(SUM(c.total_duration_ms), 0)"
        " FROM aihelms.cost_summary_daily c"
        f"{_PLATFORM_MODEL_JOIN}"
        " WHERE c.user_id = :user_id AND c.summary_date >= :start AND c.summary_date <= :end"
        " AND c.cost_type = 'llm' AND c.model IS NOT NULL"
        " GROUP BY c.model, m.name, m.model_id"
        " ORDER BY 12 DESC"
    )
    result = await session.execute(
        sql, {"user_id": user_id, "start": start_date, "end": end_date}
    )
    return [
        {
            "model": r[0],
            "platform_model_name": r[1],
            "platform_model_id": r[2],
            "request_count": int(r[3]),
            "successful_requests": int(r[4]),
            "input_tokens": int(r[5]),
            "output_tokens": int(r[6]),
            "cache_read_tokens": int(r[7]),
            "cache_creation_tokens": int(r[8]),
            "fresh_input_tokens": int(r[9]),
            "internal_cost": float(r[10]),
            "total_duration_ms": int(r[11]),
        }
        for r in result.fetchall()
    ]


async def get_user_model_latency(
    session: AsyncSession, start_date: date, end_date: date, user_id: int
) -> list[dict]:
    speed_eligible = (
        "duration_ms IS NOT NULL AND ttft_ms IS NOT NULL"
        " AND ttft_ms >= 0 AND duration_ms > ttft_ms"
    )
    sql = text(
        "SELECT model,"
        f" COALESCE(SUM(completion_tokens) FILTER (WHERE {speed_eligible}), 0) AS speed_output_tokens,"
        f" COALESCE(SUM(duration_ms - ttft_ms) FILTER (WHERE {speed_eligible}), 0) AS speed_decode_ms,"
        f" COUNT(*) FILTER (WHERE {speed_eligible}) AS speed_samples,"
        " PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ttft_ms) AS first_token_ms"
        " FROM aihelms.llm_call_logs"
        " WHERE user_id = :user_id AND status = 'success'"
        " AND started_at::date >= :start AND started_at::date <= :end"
        " GROUP BY model"
    )
    result = await session.execute(
        sql, {"user_id": user_id, "start": start_date, "end": end_date}
    )
    return [
        {
            "model": r[0],
            "speed_output_tokens": int(r[1]),
            "speed_decode_ms": int(r[2]),
            "speed_samples": int(r[3]),
            "first_token_ms": float(r[4]) if r[4] is not None else None,
        }
        for r in result.fetchall()
    ]


async def get_cost_detail_by_user(
    session: AsyncSession,
    start_date: date,
    end_date: date,
    cost_type: str | None = None,
    department_id=None,
    project_id=None,
) -> list[dict]:
    filters, params = _build_cost_filters(
        start_date, end_date, cost_type, department_id, "c", project_id
    )
    sql = text(
        "WITH RECURSIVE all_paths AS ("
        " SELECT id, name, parent_id, name::text AS path"
        " FROM aihelms.departments WHERE parent_id IS NULL"
        " UNION ALL"
        " SELECT d.id, d.name, d.parent_id, (ap.path || ' / ' || d.name)::text"
        " FROM aihelms.departments d JOIN all_paths ap ON ap.id = d.parent_id"
        " ), user_dept AS ("
        " SELECT DISTINCT ON (ud.user_id) ud.user_id, ap.path"
        " FROM aihelms.user_departments ud"
        " JOIN all_paths ap ON ap.id = ud.department_id"
        " ORDER BY ud.user_id, length(ap.path) DESC"
        " )"
        " SELECT c.user_id,"
        " COALESCE(NULLIF(u.display_name, ''), u.username, '已删除用户') AS user_name,"
        " COALESCE(udp.path, '') AS department,"
        " COALESCE(SUM(c.internal_cost) FILTER (WHERE c.cost_type = 'llm'), 0) AS llm_cost,"
        " COALESCE(SUM(c.internal_cost) FILTER (WHERE c.cost_type = 'mcp'), 0) AS mcp_cost,"
        " COALESCE(SUM(c.internal_cost), 0),"
        " COALESCE(SUM(c.external_cost), 0),"
        " COALESCE(SUM(c.total_requests), 0),"
        " COALESCE(SUM(c.successful_requests), 0),"
        " COALESCE(SUM(c.input_tokens), 0),"
        " COALESCE(SUM(c.output_tokens), 0),"
        " COALESCE(SUM(c.cache_read_tokens), 0),"
        " COALESCE(SUM(c.cache_creation_tokens), 0),"
        " COALESCE(SUM(GREATEST(c.input_tokens - c.cache_read_tokens, 0)), 0)"
        " FROM aihelms.cost_summary_daily c"
        " LEFT JOIN aihelms.users u ON u.id = c.user_id"
        " LEFT JOIN user_dept udp ON udp.user_id = c.user_id"
        f" {filters} AND c.user_id IS NOT NULL"
        " GROUP BY c.user_id, u.display_name, u.username, udp.path"
        " ORDER BY 6 DESC"
    )
    result = await session.execute(sql, params)
    return [
        {
            "user_id": int(r[0]),
            "user_name": r[1],
            "department": r[2] or "",
            "llm_cost": float(r[3]),
            "mcp_cost": float(r[4]),
            "internal_cost": float(r[5]),
            "external_cost": float(r[6]),
            "cost_diff": round(float(r[5]) - float(r[6]), 4),
            "requests": int(r[7]),
            "successful_requests": int(r[8]),
            "input_tokens": int(r[9]),
            "output_tokens": int(r[10]),
            "cache_read_tokens": int(r[11]),
            "cache_creation_tokens": int(r[12]),
            "fresh_input_tokens": int(r[13]),
        }
        for r in result.fetchall()
    ]
