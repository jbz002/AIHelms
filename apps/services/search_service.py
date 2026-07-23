"""Search service — RRF fusion, soft-cap, governance filtering, result assembly.

Combines results from multiple entity types, applies Reciprocal Rank Fusion
(DDF) with per-signal scoring, enforces soft-cap diversity constraint,
and assembles structured search results with match_context.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from repositories import search_repo

RRF_K: int = 60
SOFT_CAP_RATIO: float = 0.6


@dataclass
class MatchContext:
    matched_fields: list[str]
    matched_text: str


@dataclass
class SearchResultItem:
    entity_type: str
    entity_id: int
    name: str
    description: str
    relevance_score: float
    match_context: MatchContext
    metadata: dict


def _soft_cap_distribute(
    scored: list[tuple[SearchResultItem, float]],
) -> list[tuple[SearchResultItem, float]]:
    """Distribute results enforcing soft-cap per entity type.

    No single entity type can occupy more than ceil(total * 0.6) slots.
    Two-pass algorithm:
      Pass 1: assign results in order, skip when type cap exceeded.
      Pass 2: fill remaining slots from skipped items.
    """
    import math

    total = len(scored)
    if total == 0:
        return []

    cap = math.ceil(total * SOFT_CAP_RATIO)
    counts: dict[str, int] = {}
    accepted: list[tuple[SearchResultItem, float]] = []
    skipped: list[tuple[SearchResultItem, float]] = []

    for item, score in scored:
        etype = item.entity_type
        counts[etype] = counts.get(etype, 0) + 1
        if counts[etype] <= cap:
            accepted.append((item, score))
        else:
            skipped.append((item, score))

    # If we filled all slots, done
    if len(accepted) >= total:
        return accepted

    # Fill remaining from skipped
    for item, score in skipped:
        if len(accepted) < total:
            accepted.append((item, score))
        else:
            break

    return accepted


async def unified_search(
    session: AsyncSession,
    keyword: str,
    entity_types: list[str] | None = None,
    category: str | None = None,
    is_published: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Unified cross-entity search with RRF fusion.

    1. Search each entity type independently → ranked lists
    2. RRF fusion across types
    3. Soft-cap distribution
    4. Pagination + assemble results
    """
    etypes = entity_types or ["mcp_server", "skill"]

    # Phase 1: independent searches per entity type
    candidates: dict[str, list[search_repo.SearchResult]] = {}

    if "mcp_server" in etypes:
        candidates["mcp_server"] = await search_repo.search_mcp_servers(
            session, keyword, category=category, is_published=is_published, limit=100
        )

    if "mcp_tool" in etypes:
        candidates["mcp_tool"] = await search_repo.search_mcp_tools(
            session, keyword, limit=100
        )

    if "skill" in etypes:
        candidates["skill"] = await search_repo.search_skills(
            session, keyword, category=category, is_published=is_published, limit=100
        )

    # Phase 2: RRF fusion
    items = _rrf_fuse(candidates)

    # Phase 3: soft-cap distribution
    items = _soft_cap_distribute(items)

    # Phase 4: pagination
    total = len(items)
    offset = (page - 1) * page_size
    page_items = items[offset : offset + page_size]

    # Phase 5: assemble output
    results = []
    for item, _ in page_items:
        results.append(
            {
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "name": item.name,
                "description": item.description,
                "relevance_score": round(item.relevance_score, 4),
                "match_context": {
                    "matched_fields": item.match_context.matched_fields,
                    "matched_text": keyword,
                },
                "metadata": item.metadata,
            }
        )

    return {
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _rrf_fuse(
    candidates: dict[str, list[search_repo.SearchResult]],
) -> list[tuple[SearchResultItem, float]]:
    """Reciprocal Rank Fusion across entity type result lists.

    RRF formula: score(doc) = sum over lists: 1 / (k + rank),
    where rank starts at 1.
    """
    scores: dict[tuple[str, int], float] = {}

    for entity_type, items in candidates.items():
        for rank, item in enumerate(items):
            key = (entity_type, item.entity_id)
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)

    # Build SearchResultItem objects with metadata
    results: list[tuple[SearchResultItem, float]] = []
    for key, rrf_score in scores.items():
        entity_type, entity_id = key
        # Get original search result for metadata
        src_items = candidates.get(entity_type, [])
        src = next((i for i in src_items if i.entity_id == entity_id), None)
        if not src:
            continue

        # Assemble basic info from search result
        name, description = _get_entity_info(entity_type, src)
        relevance = rrf_score + src.signal_score * 0.01  # Combine RRF + signal

        item = SearchResultItem(
            entity_type=entity_type,
            entity_id=entity_id,
            name=name,
            description=description,
            relevance_score=relevance,
            match_context=MatchContext(
                matched_fields=src.matched_fields,
                matched_text="",
            ),
            metadata=_build_metadata(entity_type, src),
        )
        results.append((item, relevance))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def _get_entity_info(
    entity_type: str, src: search_repo.SearchResult
) -> tuple[str, str]:
    """Get display name and description from search result."""
    return src.name, src.description


def _build_metadata(entity_type: str, src: search_repo.SearchResult) -> dict:
    """Build metadata dict for the search result."""
    if entity_type == "mcp_server":
        return {
            "entity_type": "mcp_server",
            "entity_id": src.entity_id,
            "matched_fields": src.matched_fields,
            "signal_score": round(src.signal_score, 2),
        }
    if entity_type == "mcp_tool":
        return {
            "entity_type": "mcp_tool",
            "entity_id": src.entity_id,
            "server_id": src.server_id,
            "matched_fields": src.matched_fields,
            "signal_score": round(src.signal_score, 2),
        }
    if entity_type == "skill":
        return {
            "entity_type": "skill",
            "entity_id": src.entity_id,
            "matched_fields": src.matched_fields,
            "signal_score": round(src.signal_score, 2),
        }
    return {
        "entity_type": entity_type,
        "entity_id": src.entity_id,
    }
