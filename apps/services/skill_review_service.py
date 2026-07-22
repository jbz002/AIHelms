"""S3 · 版本级审核任务工作流（skill_review_tasks）。

只管审核任务表本身：创建/审批/拒绝/撤回 + 乐观锁 + 防自审 + auto-withdraw。
版本生命周期翻转（pending_review → published/rejected）由 skill_service 编排，
本服务不触碰 SkillVersion 与 skills 指针，避免循环导入与职责越界。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, ForbiddenError, ValidationError
from models.db import SkillReviewTask
from repositories import skill_review_repo

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
WITHDRAWN = "withdrawn"


async def submit(
    session: AsyncSession, version_id: int, submitted_by: int
) -> SkillReviewTask:
    """提交审核：auto-withdraw 该版本旧 pending task，再新建 pending task。

    先显式 flush 撤回 UPDATE，避免 SQLAlchemy 把新 pending INSERT 排在 UPDATE 前
    触发部分唯一索引 uq_skill_review_tasks_pending 冲突。
    """
    await skill_review_repo.withdraw_pending_by_version(session, version_id)
    await session.flush()
    task = SkillReviewTask(
        skill_version_id=version_id,
        status=PENDING,
        submitted_by=submitted_by,
    )
    return await skill_review_repo.create(session, task)


def _assert_pending(task: SkillReviewTask) -> None:
    if task.status != PENDING:
        raise ConflictError(f"审核任务当前状态为 {task.status}，不可处理")


def _assert_not_self_review(reviewer_id: int, submitted_by: int) -> None:
    if reviewer_id == submitted_by:
        raise ForbiddenError("不可审核自己提交的版本")


async def approve(
    session: AsyncSession,
    task: SkillReviewTask,
    reviewer_id: int,
    decision_notes: str = "",
) -> SkillReviewTask:
    """通过审核（乐观锁 + 防自审）。版本激活由调用方编排。"""
    _assert_pending(task)
    _assert_not_self_review(reviewer_id, task.submitted_by)
    return await skill_review_repo.resolve_with_lock(
        session,
        task.id,
        task.lock_version,
        status=APPROVED,
        reviewer_id=reviewer_id,
        decision_notes=decision_notes,
    )


async def reject(
    session: AsyncSession,
    task: SkillReviewTask,
    reviewer_id: int,
    decision_notes: str = "",
) -> SkillReviewTask:
    """拒绝审核（乐观锁 + 防自审）。版本转 rejected 由调用方编排。"""
    _assert_pending(task)
    _assert_not_self_review(reviewer_id, task.submitted_by)
    return await skill_review_repo.resolve_with_lock(
        session,
        task.id,
        task.lock_version,
        status=REJECTED,
        reviewer_id=reviewer_id,
        decision_notes=decision_notes,
    )


async def withdraw(
    session: AsyncSession, task: SkillReviewTask, actor_id: int
) -> SkillReviewTask:
    """撤回审核：仅提交人本人可撤回。"""
    _assert_pending(task)
    if actor_id != task.submitted_by:
        raise ForbiddenError("仅提交人可撤回审核")
    return await skill_review_repo.resolve_with_lock(
        session,
        task.id,
        task.lock_version,
        status=WITHDRAWN,
        reviewer_id=actor_id,
        decision_notes="提交人撤回",
    )


async def get_pending_for_version(
    session: AsyncSession, version_id: int
) -> SkillReviewTask | None:
    return await skill_review_repo.find_pending_by_version(session, version_id)


async def require_pending_for_version(
    session: AsyncSession, version_id: int
) -> SkillReviewTask:
    task = await skill_review_repo.find_pending_by_version(session, version_id)
    if task is None:
        raise ValidationError("该版本没有待处理的审核任务")
    return task
