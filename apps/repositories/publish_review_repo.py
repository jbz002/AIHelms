"""发布评审 repository（模块 07 发布门控）。

提交发布申请 → 管理员审核 → 置资源 is_published。
状态：pending / approved / rejected / withdrawn。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import PublishReview

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_WITHDRAWN = "withdrawn"


async def create_review(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
    requested_by: int,
) -> PublishReview:
    review = PublishReview(
        entity_type=entity_type,
        entity_id=entity_id,
        requested_by=requested_by,
        status=STATUS_PENDING,
    )
    session.add(review)
    await session.flush()
    await session.refresh(review)
    return review


async def find_by_id(session: AsyncSession, review_id: int) -> PublishReview | None:
    return await session.get(PublishReview, review_id)


async def find_pending_by_entity(
    session: AsyncSession, entity_type: str, entity_id: int
) -> PublishReview | None:
    result = await session.execute(
        select(PublishReview).where(
            PublishReview.entity_type == entity_type,
            PublishReview.entity_id == entity_id,
            PublishReview.status == STATUS_PENDING,
        )
    )
    return result.scalar_one_or_none()


async def list_reviews(
    session: AsyncSession,
    status: str | None = None,
    entity_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[PublishReview], int]:
    filters = []
    if status:
        filters.append(PublishReview.status == status)
    if entity_type:
        filters.append(PublishReview.entity_type == entity_type)

    count_stmt = select(func.count(PublishReview.id))
    list_stmt = select(PublishReview).order_by(PublishReview.created_at.desc())
    for flt in filters:
        count_stmt = count_stmt.where(flt)
        list_stmt = list_stmt.where(flt)

    total = int((await session.execute(count_stmt)).scalar_one())
    offset = (page - 1) * page_size
    list_stmt = list_stmt.limit(page_size).offset(offset)
    items = list((await session.execute(list_stmt)).scalars().all())
    return items, total
