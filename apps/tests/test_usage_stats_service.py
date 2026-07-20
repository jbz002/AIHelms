"""使用统计 service 集成测试（走真实 DB）。

覆盖：MCP 哨兵 0 排除、双 cost 列求和、skill 动作拆分、trend 零填充。
日志表 server_id/skill_id 无 FK，测试用任意 id，用完清理。
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import delete

from core.database import get_worker_session_factory
from models.db import McpCallLog, SkillUsageLog
from services import usage_stats_service


def _session():
    return get_worker_session_factory()()


async def _cleanup_logs(server_id: int, skill_id: int) -> None:
    async with _session() as s:
        await s.execute(delete(McpCallLog).where(McpCallLog.server_id == server_id))
        await s.execute(delete(SkillUsageLog).where(SkillUsageLog.skill_id == skill_id))
        await s.commit()


@pytest.mark.asyncio
async def test_mcp_stats_excludes_sentinel_user_and_sums_both_costs():
    server_id = abs(hash(uuid.uuid4())) % 10**9
    skill_id = abs(hash(uuid.uuid4())) % 10**9
    try:
        async with _session() as s:
            # 3 行：两个真实用户 + 1 个哨兵 0；internal+external 双 cost
            for uid, ic, ec in [(101, 1.0, 0.5), (102, 2.0, 0.0), (0, 5.0, 5.0)]:
                s.add(
                    McpCallLog(
                        user_id=uid,
                        server_id=server_id,
                        tool_name="t",
                        namespaced_tool_name="srv/t",
                        internal_cost=ic,
                        external_cost=ec,
                        duration_ms=100,
                        called_at=date.today(),
                    )
                )
            await s.commit()

        async with _session() as s:
            stats = await usage_stats_service.mcp_usage_stats(s, server_id, days=7)
        assert stats["total_calls"] == 3
        assert stats["unique_users"] == 2  # 哨兵 0 排除
        assert stats["total_cost"] == 13.5  # (1.0+0.5)+(2.0+0.0)+(5.0+5.0)
        assert stats["avg_duration_ms"] == 100
    finally:
        await _cleanup_logs(server_id, skill_id)


@pytest.mark.asyncio
async def test_skill_stats_action_split():
    server_id = abs(hash(uuid.uuid4())) % 10**9
    skill_id = abs(hash(uuid.uuid4())) % 10**9
    try:
        async with _session() as s:
            for action in ["download", "download", "agent_download"]:
                s.add(
                    SkillUsageLog(
                        user_id=201,
                        skill_id=skill_id,
                        action=action,
                        created_at=date.today(),
                    )
                )
            await s.commit()

        async with _session() as s:
            stats = await usage_stats_service.skill_usage_stats(s, skill_id, days=7)
        assert stats["total_downloads"] == 3
        assert stats["manual_downloads"] == 2
        assert stats["agent_downloads"] == 1
        assert stats["unique_users"] == 1
    finally:
        await _cleanup_logs(server_id, skill_id)


@pytest.mark.asyncio
async def test_trend_zero_fills_missing_days():
    server_id = abs(hash(uuid.uuid4())) % 10**9
    skill_id = abs(hash(uuid.uuid4())) % 10**9
    try:
        old_day = date.today() - timedelta(days=5)
        async with _session() as s:
            s.add(
                McpCallLog(
                    user_id=301,
                    server_id=server_id,
                    tool_name="t",
                    namespaced_tool_name="srv/t",
                    called_at=old_day,
                )
            )
            await s.commit()

        async with _session() as s:
            stats = await usage_stats_service.mcp_usage_stats(s, server_id, days=7)
        # 7 天窗口，仅 1 天有数据，其余零填充
        assert len(stats["trend"]) == 7
        non_zero = [p for p in stats["trend"] if p["count"] > 0]
        assert len(non_zero) == 1
        assert non_zero[0]["count"] == 1
    finally:
        await _cleanup_logs(server_id, skill_id)
