"""发布评审 service（模块 07 发布门控）。

流程：创建者提交发布申请（pending）→ 管理员审核通过则置资源 is_published=true；
驳回退回草稿附备注；创建者可撤回。

与 resource_application_service 正交：
- resource_application = 用户申请「使用」资源（消费者，批准后授权到其 key）
- publish_review = 创建者申请「发布」资源（作者，批准后 is_published=true）
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, NotFoundError, ValidationError
from repositories import publish_review_repo

ENTITY_MCP = "mcp_server"
ENTITY_SKILL = "skill"
ENTITY_CUSTOM = "custom_entity"
VALID_ENTITY_TYPES: tuple[str, ...] = (ENTITY_MCP, ENTITY_SKILL, ENTITY_CUSTOM)


async def submit_review(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
    requested_by: int,
):
    """创建者提交发布申请。同一资源已有 pending 时拒绝。"""
    if entity_type not in VALID_ENTITY_TYPES:
        raise ValidationError(f"不支持的实体类型: {entity_type}")
    existing = await publish_review_repo.find_pending_by_entity(
        session, entity_type, entity_id
    )
    if existing:
        raise ConflictError("该资源已有待审核的发布申请")
    review = await publish_review_repo.create_review(
        session, entity_type, entity_id, requested_by
    )
    await session.commit()
    await session.refresh(review)
    return review


async def resolve_publish(
    session: AsyncSession, want_publish: bool
) -> tuple[bool, bool]:
    """门控决策。返回 (effective_is_published, should_submit_review)。

    gate 关 → (want_publish, False)；gate 开 + want_publish → (False, True)。
    """
    if not want_publish:
        return False, False
    from services import publish_settings_service

    if await publish_settings_service.is_gate_enabled(session):
        return False, True
    return True, False


async def approve(
    session: AsyncSession,
    review_id: int,
    reviewer_id: int,
    notes: str = "",
):
    """审核通过：置资源 is_published=true + 评审单 approved。"""
    review = await publish_review_repo.find_by_id(session, review_id)
    if not review:
        raise NotFoundError("publish_review", review_id)
    if review.status != publish_review_repo.STATUS_PENDING:
        raise ConflictError(f"发布申请当前状态为 {review.status}，无法审核通过")
    await _set_entity_published(session, review.entity_type, review.entity_id, True)
    review.status = publish_review_repo.STATUS_APPROVED
    review.reviewed_by = reviewer_id
    review.reviewed_at = datetime.now(timezone.utc)
    if notes:
        review.review_notes = notes
    await session.flush()
    await session.commit()
    await session.refresh(review)
    return review


async def reject(
    session: AsyncSession,
    review_id: int,
    reviewer_id: int,
    notes: str = "",
):
    """审核驳回：退回草稿（资源保持未发布）+ 评审单 rejected。"""
    review = await publish_review_repo.find_by_id(session, review_id)
    if not review:
        raise NotFoundError("publish_review", review_id)
    if review.status != publish_review_repo.STATUS_PENDING:
        raise ConflictError(f"发布申请当前状态为 {review.status}，无法驳回")
    review.status = publish_review_repo.STATUS_REJECTED
    review.reviewed_by = reviewer_id
    review.reviewed_at = datetime.now(timezone.utc)
    if notes:
        review.review_notes = notes
    await session.flush()
    await session.commit()
    await session.refresh(review)
    return review


async def withdraw(session: AsyncSession, review_id: int, requester_id: int):
    """创建者撤回自己的 pending 申请。"""
    review = await publish_review_repo.find_by_id(session, review_id)
    if not review:
        raise NotFoundError("publish_review", review_id)
    if review.requested_by != requester_id:
        raise ValidationError("只能撤回自己的发布申请")
    if review.status != publish_review_repo.STATUS_PENDING:
        raise ConflictError(f"发布申请当前状态为 {review.status}，无法撤回")
    review.status = publish_review_repo.STATUS_WITHDRAWN
    await session.flush()
    await session.commit()
    await session.refresh(review)
    return review


async def get_review(session: AsyncSession, review_id: int) -> dict:
    review = await publish_review_repo.find_by_id(session, review_id)
    if not review:
        raise NotFoundError("publish_review", review_id)
    return _serialize(review)


async def list_reviews(
    session: AsyncSession,
    status: str | None = None,
    entity_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    items, total = await publish_review_repo.list_reviews(
        session, status, entity_type, page, page_size
    )
    return {
        "items": [_serialize(r) for r in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _set_entity_published(
    session: AsyncSession, entity_type: str, entity_id: int, value: bool
) -> None:
    """按实体类型分派置 is_published。延迟 import 避免循环依赖。"""
    if entity_type == ENTITY_MCP:
        from services import mcp_service

        await mcp_service.set_published(session, entity_id, value)
    elif entity_type == ENTITY_SKILL:
        from services import skill_service

        await skill_service.set_published(session, entity_id, value)
    elif entity_type == ENTITY_CUSTOM:
        from services import custom_entity_service

        await custom_entity_service.set_published(session, entity_id, value)
    else:
        raise ValidationError(f"不支持的实体类型: {entity_type}")


def _fmt(dt) -> str | None:
    return dt.isoformat() if dt else None


def _serialize(review) -> dict:
    return {
        "id": review.id,
        "entity_type": review.entity_type,
        "entity_id": review.entity_id,
        "requested_by": review.requested_by,
        "status": review.status,
        "review_notes": review.review_notes,
        "reviewed_by": review.reviewed_by,
        "reviewed_at": _fmt(review.reviewed_at),
        "created_at": _fmt(review.created_at),
        "updated_at": _fmt(review.updated_at),
    }
