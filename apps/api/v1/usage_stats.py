"""使用统计 router。聚合平台落库日志（mcp_call_logs / skill_usage_logs）。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_current_user, get_db
from services import usage_stats_service

router = APIRouter(prefix="/stats", tags=["使用统计"])


@router.get("/mcp/{server_id}", summary="获取 MCP 使用统计")
async def get_mcp_usage_stats(
    server_id: int,
    days: int = Query(30, pattern=r"^(7|30|90)$"),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    data = await usage_stats_service.mcp_usage_stats(session, server_id, days)
    return {"code": 200, "message": "ok", "data": data}


@router.get("/skill/{skill_id}", summary="获取 Skill 使用统计")
async def get_skill_usage_stats(
    skill_id: int,
    days: int = Query(30, pattern=r"^(7|30|90)$"),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    data = await usage_stats_service.skill_usage_stats(session, skill_id, days)
    return {"code": 200, "message": "ok", "data": data}
