"""Unified search API — POST /api/v1/search.

Cross-entity word-level search with RRF fusion.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_current_user, get_db
from services import search_service

router = APIRouter(tags=["AI 市场"])


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=512, description="Search keyword")
    entity_types: list[str] | None = None
    category: str | None = None


@router.post("", summary="统一搜索")
async def search(
    req: SearchRequest = Body(..., description="Search query"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Unified search across MCP Server, Skill and Agent.

    Users see published assets only.
    """
    # Default to all entity types
    entity_types = req.entity_types or ["mcp_server", "skill", "agent"]

    data = await search_service.unified_search(
        session=session,
        keyword=req.q,
        entity_types=entity_types,
        category=req.category,
        is_published=True,  # Users see published only
        page=page,
        page_size=page_size,
    )
    return {"code": 200, "message": "ok", "data": data}
