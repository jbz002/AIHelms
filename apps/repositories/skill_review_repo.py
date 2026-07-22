from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError
from models.db import SkillReviewTask


async def create(session: AsyncSession, task: SkillReviewTask) -> SkillReviewTask:
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return task


async def find_pending_by_version(
    session: AsyncSession, version_id: int
) -> SkillReviewTask | None:
    result = await session.execute(
        select(SkillReviewTask).where(
            SkillReviewTask.skill_version_id == version_id,
            SkillReviewTask.status == "pending",
        )
    )
    return result.scalar_one_or_none()


async def find_latest_for_version(
    session: AsyncSession, version_id: int
) -> SkillReviewTask | None:
    """该版本最新一条审核任务（任意状态）。激活门控据此判断是否存在 approved。"""
    result = await session.execute(
        select(SkillReviewTask)
        .where(SkillReviewTask.skill_version_id == version_id)
        .order_by(SkillReviewTask.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def withdraw_pending_by_version(session: AsyncSession, version_id: int) -> None:
    """auto-withdraw：版本重传/重新提交审核时，旧 pending task 批量降级为 withdrawn。"""
    await session.execute(
        update(SkillReviewTask)
        .where(
            SkillReviewTask.skill_version_id == version_id,
            SkillReviewTask.status == "pending",
        )
        .values(status="withdrawn", resolved_at=datetime.now(timezone.utc))
    )


async def find_by_id(session: AsyncSession, task_id: int) -> SkillReviewTask | None:
    result = await session.execute(
        select(SkillReviewTask).where(SkillReviewTask.id == task_id)
    )
    return result.scalar_one_or_none()


async def resolve_with_lock(
    session: AsyncSession,
    task_id: int,
    expected_lock_version: int,
    *,
    status: str,
    reviewer_id: int,
    decision_notes: str,
) -> SkillReviewTask:
    """乐观锁审批/拒绝：lock_version 不匹配 → ConflictError。

    approved / rejected / withdrawn 共用本函数，status 由调用方决定。
    """
    result = await session.execute(
        update(SkillReviewTask)
        .where(
            SkillReviewTask.id == task_id,
            SkillReviewTask.lock_version == expected_lock_version,
        )
        .values(
            status=status,
            reviewer_id=reviewer_id,
            decision_notes=decision_notes,
            resolved_at=datetime.now(timezone.utc),
            lock_version=expected_lock_version + 1,
        )
        .returning(SkillReviewTask)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ConflictError("审核任务已被他人处理，请刷新重试")
    return row
