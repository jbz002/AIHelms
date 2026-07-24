"""S3 · Skill 版本生命周期状态机：合法流转校验。

新状态机（替换旧 3 态 inactive/active/deprecated）：
    draft → scanning → pending_review → published
    scanning → rejected / draft
    pending_review → rejected
    published → yanked / deprecated

is_active 由 published 派生（published=True，其余 False）。terminal 态：
yanked / rejected / deprecated 无合法出边。

本模块只做纯校验（无 DB/无副作用），供 skill_service /
ai_policies_service 复用，避免循环导入。实际 DB 翻转与 Yank 指针重算在 skill_service。
"""

from exceptions import ValidationError

# 7 态取值
DRAFT = "draft"
SCANNING = "scanning"
PENDING_REVIEW = "pending_review"
PUBLISHED = "published"
YANKED = "yanked"
REJECTED = "rejected"
DEPRECATED = "deprecated"

ALL_STATUSES: tuple[str, ...] = (
    DRAFT,
    SCANNING,
    PENDING_REVIEW,
    PUBLISHED,
    YANKED,
    REJECTED,
    DEPRECATED,
)

# 合法出边
_TRANSITIONS: dict[str, set[str]] = {
    DRAFT: {SCANNING, PENDING_REVIEW, PUBLISHED},
    SCANNING: {PENDING_REVIEW, REJECTED, DRAFT},
    PENDING_REVIEW: {PUBLISHED, REJECTED, DRAFT},
    PUBLISHED: {YANKED, DEPRECATED},
    YANKED: set(),
    REJECTED: set(),
    DEPRECATED: set(),
}

# is_active 派生：仅 published 为 True
ACTIVE_LIKE_STATUSES: frozenset[str] = frozenset({PUBLISHED})


def is_published(status: str) -> bool:
    return status == PUBLISHED


def assert_transition(current: str, target: str) -> None:
    """校验 current→target 合法，非法抛 ValidationError。"""
    if current not in ALL_STATUSES:
        raise ValidationError(f"未知生命周期状态：{current}")
    if target not in _TRANSITIONS.get(current, set()):
        raise ValidationError(f"非法状态流转：{current} → {target}")


def derives_is_active(status: str) -> bool:
    """is_active 由 lifecycle_status 派生。"""
    return status in ACTIVE_LIKE_STATUSES
