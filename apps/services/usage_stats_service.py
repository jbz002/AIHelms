"""使用统计 service。日期范围解析 + trend 零填充，调 usage_stats_repo。"""

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from repositories import usage_stats_repo

_VALID_DAYS = (7, 30, 90)


def _resolve_range(days: int) -> tuple[date, date]:
    today = date.today()
    start = today - timedelta(days=days - 1)
    return start, today


def _zero_fill_trend(
    rows: list[tuple[date, int]], start: date, end: date
) -> list[dict]:
    days = (end - start).days + 1
    bucket = {start + timedelta(days=i): 0 for i in range(days)}
    for day, cnt in rows:
        bucket[day] = cnt
    return [{"date": day.isoformat(), "count": cnt} for day, cnt in bucket.items()]


async def mcp_usage_stats(
    session: AsyncSession, server_id: int, days: int = 30
) -> dict:
    if days not in _VALID_DAYS:
        days = 30
    start, end = _resolve_range(days)
    totals = await usage_stats_repo.mcp_totals(session, server_id, start)
    trend_rows = await usage_stats_repo.mcp_trend(session, server_id, start)
    tools = await usage_stats_repo.mcp_tool_distribution(session, server_id, start)
    return {
        **totals,
        "trend": _zero_fill_trend(trend_rows, start, end),
        "tool_distribution": [{"tool_name": name, "count": cnt} for name, cnt in tools],
    }


async def skill_usage_stats(
    session: AsyncSession, skill_id: int, days: int = 30
) -> dict:
    if days not in _VALID_DAYS:
        days = 30
    start, end = _resolve_range(days)
    totals = await usage_stats_repo.skill_totals(session, skill_id, start)
    trend_rows = await usage_stats_repo.skill_trend(session, skill_id, start)
    actions = await usage_stats_repo.skill_action_distribution(session, skill_id, start)
    return {
        **totals,
        "trend": _zero_fill_trend(trend_rows, start, end),
        "action_distribution": [
            {"action": action, "count": cnt} for action, cnt in actions
        ],
    }
