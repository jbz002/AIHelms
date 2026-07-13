"""Search repository — ILIKE-based word-level search with signal weights.

Each search function returns matched items sorted by signal score
(weighted sum of matched fields), then limit.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import McpServer, McpTool, Skill


@dataclass
class SearchResult:
    entity_id: int
    signal_score: float
    matched_fields: list[str]
    name: str = ""
    description: str = ""
    server_id: int | None = None


async def search_mcp_servers(
    session: AsyncSession,
    keyword: str,
    category: str | None = None,
    is_published: bool | None = None,
    limit: int = 100,
) -> list[SearchResult]:
    """Search MCP Servers by keyword across name, description, tags, author.

    Returns results sorted by weighted signal score, limited.
    """
    kw = f"%{keyword}%"

    stmt = select(
        McpServer.id,
        McpServer.call_count,
        McpServer.name.label("_name"),
        McpServer.description.label("_desc"),
        McpServer.tags.label("_tags"),
        McpServer.author.label("_author"),
        func.coalesce(
            McpServer.name.ilike(kw).cast(int) * 3.0
            + McpServer.server_name.ilike(kw).cast(int) * 3.0
            + McpServer.description.ilike(kw).cast(int) * 2.0
            + McpServer.tags.astext.ilike(kw).cast(int) * 1.5
            + McpServer.author.ilike(kw).cast(int) * 1.0,
            0.0,
        ).label("_score"),
    ).where(McpServer.is_active)

    if category:
        stmt = stmt.where(McpServer.category == category)
    if is_published is not None:
        stmt = stmt.where(McpServer.is_published == is_published)

    stmt = stmt.where(
        or_(
            McpServer.name.ilike(kw),
            McpServer.server_name.ilike(kw),
            McpServer.description.ilike(kw),
            McpServer.author.ilike(kw),
            McpServer.tags.astext.ilike(kw),
        )
    )

    stmt = stmt.order_by(func["_score"].desc()).limit(limit)
    result = await session.execute(stmt)
    rows = result.all()

    kw_lower = keyword.lower()
    out: list[SearchResult] = []
    for row in rows:
        matched: list[str] = []
        n = row._name
        if n and kw_lower in n.lower():
            matched.append("name")
        if row._desc and kw_lower in row._desc.lower():
            matched.append("description")
        out.append(
            SearchResult(
                entity_id=row.id,
                signal_score=float(row._score),
                matched_fields=matched,
                name=row._name or "",
                description=row._desc or "",
            )
        )
    return out


async def search_mcp_tools(
    session: AsyncSession,
    keyword: str,
    limit: int = 100,
) -> list[SearchResult]:
    """Search MCP Tools by keyword across tool_name, display_name, description.

    Returns results with server_id so we can link to parent server.
    """
    kw = f"%{keyword}%"
    kw_lower = keyword.lower()

    stmt = select(
        McpTool.id,
        McpTool.tool_name,
        McpTool.display_name,
        McpTool.namespaced_name,
        McpTool.description,
        McpTool.server_id,
        func.coalesce(
            McpTool.tool_name.ilike(kw).cast(int) * 3.0
            + McpTool.display_name.ilike(kw).cast(int) * 3.0
            + McpTool.namespaced_name.ilike(kw).cast(int) * 3.0
            + McpTool.description.ilike(kw).cast(int) * 2.0,
            0.0,
        ).label("_score"),
    ).where(McpTool.is_active)

    stmt = stmt.where(
        or_(
            McpTool.tool_name.ilike(kw),
            McpTool.display_name.ilike(kw),
            McpTool.namespaced_name.ilike(kw),
            McpTool.description.ilike(kw),
        )
    )

    stmt = stmt.order_by(func["_score"].desc()).limit(limit)
    result = await session.execute(stmt)
    rows = result.all()

    out: list[SearchResult] = []
    for row in rows:
        matched: list[str] = []
        tn = row.tool_name
        if kw_lower in tn.lower():
            matched.append("tool_name")
        dn = row.display_name
        if dn and kw_lower in dn.lower():
            matched.append("display_name")
        desc = row.description
        if desc and kw_lower in desc.lower():
            matched.append("description")
        out.append(
            SearchResult(
                entity_id=row.id,
                signal_score=float(row._score),
                matched_fields=matched,
                name=dn or tn,
                description=desc or "",
                server_id=row.server_id,
            )
        )
    return out


async def search_skills(
    session: AsyncSession,
    keyword: str,
    category: str | None = None,
    is_published: bool | None = None,
    limit: int = 100,
) -> list[SearchResult]:
    """Search Skills by keyword across name, description, tags, author."""
    kw = f"%{keyword}%"
    kw_lower = keyword.lower()

    stmt = select(
        Skill.id,
        Skill.name,
        Skill.description,
        Skill.tags,
        Skill.author,
        Skill.install_count,
        func.coalesce(
            Skill.name.ilike(kw).cast(int) * 3.0
            + Skill.description.ilike(kw).cast(int) * 2.0
            + Skill.tags.astext.ilike(kw).cast(int) * 1.5
            + Skill.author.ilike(kw).cast(int) * 1.0,
            0.0,
        ).label("_score"),
    ).where(Skill.is_active)

    if category:
        stmt = stmt.where(Skill.category == category)
    if is_published is not None:
        stmt = stmt.where(Skill.is_published == is_published)

    stmt = stmt.where(
        or_(
            Skill.name.ilike(kw),
            Skill.description.ilike(kw),
            Skill.author.ilike(kw),
            Skill.tags.astext.ilike(kw),
        )
    )

    stmt = stmt.order_by(func["_score"].desc()).limit(limit)
    result = await session.execute(stmt)
    rows = result.all()

    out: list[SearchResult] = []
    for row in rows:
        matched: list[str] = []
        n = row.name
        if kw_lower in n.lower():
            matched.append("name")
        desc = row.description
        if desc and kw_lower in desc.lower():
            matched.append("description")
        out.append(
            SearchResult(
                entity_id=row.id,
                signal_score=float(row._score),
                matched_fields=matched,
                name=n,
                description=desc or "",
            )
        )
    return out
