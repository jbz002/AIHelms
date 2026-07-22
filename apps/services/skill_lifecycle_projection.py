"""S3 · Lifecycle Projection 读模型。

前端不再从 status + hidden + version 拼装，统一消费后端 projection：
- headline_version      卡片展示版本（最新 published，无则最新 pending_review）
- published_version     当前 published 指针（current_version_id 指向的版本）
- owner_preview_version 所有者预览（最新版本，含 draft）
- resolution_mode       none / pending_review / scan_failed / yanked
- is_hidden             治理下架 overlay

纯函数，吃已序列化的版本字典列表（由 skill_serializers 传入），无 ORM 依赖。
"""

from typing import Any

from services.skill_lifecycle_service import (
    PENDING_REVIEW,
    PUBLISHED,
    YANKED,
)


def _latest(versions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """按 id 倒序的最新版本（调用方保证 versions 已按 id desc 排序，取首个）。"""
    return versions[0] if versions else None


def _filter_status(versions: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    return [v for v in versions if v.get("lifecycle_status") == status]


def _resolve_mode(
    headline: dict[str, Any] | None,
    versions: list[dict[str, Any]],
) -> str:
    if headline is None:
        return "none"
    if headline.get("lifecycle_status") == PENDING_REVIEW:
        return "pending_review"
    if headline.get("security_status") == "failed":
        return "scan_failed"
    if any(
        v.get("lifecycle_status") == YANKED for v in versions
    ) and not _filter_status(versions, PUBLISHED):
        return "yanked"
    return "none"


def build_projection(
    versions: list[dict[str, Any]],
    current_version_id: int | None,
    is_hidden: bool,
) -> dict[str, Any]:
    """构建 lifecycle projection。versions 须按 id 倒序排列。"""
    published = _filter_status(versions, PUBLISHED)
    pending = _filter_status(versions, PENDING_REVIEW)

    published_version: dict[str, Any] | None = None
    if current_version_id is not None:
        published_version = next(
            (v for v in published if v.get("id") == current_version_id), None
        )
    if published_version is None and published:
        published_version = published[0]

    headline = (
        published[0] if published else (pending[0] if pending else _latest(versions))
    )

    return {
        "headline_version": headline,
        "published_version": published_version,
        "owner_preview_version": _latest(versions),
        "resolution_mode": _resolve_mode(headline, versions),
        "is_hidden": is_hidden,
    }
