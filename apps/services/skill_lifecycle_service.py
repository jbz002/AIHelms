"""S3 · Skill 版本生命周期状态机：合法流转校验。

两维度正交：
    lifecycle_status — 版本在发布管线中的阶段（本模块校验合法流转）
    is_active        — 独立单指针（skill.current_version_id），标记当前生效版本

合法流转：
    draft → scanning → pending_review → published
    scanning → rejected / draft
    pending_review → published / rejected
    published → yanked / deprecated
    yanked → published（恢复；单版本撤回场景由 skill_service 重新激活指针）

published 是“已发布”容器，可多版本共存（当前激活 + 历史发布），由 is_active
区分当前生效的那一个；故 published 不蕴含 is_active。
terminal 态 rejected / deprecated 无合法出边。

本模块只做纯校验（无 DB/无副作用），供 skill_service / ai_policies_service
复用，避免循环导入。实际 DB 翻转、Yank 指针重算、Restore 智能恢复在 skill_service。
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
    YANKED: {PUBLISHED},
    REJECTED: set(),
    DEPRECATED: set(),
}


def assert_transition(current: str, target: str) -> None:
    """校验 current→target 合法，非法抛 ValidationError。"""
    if current not in ALL_STATUSES:
        raise ValidationError(f"未知生命周期状态：{current}")
    if target not in _TRANSITIONS.get(current, set()):
        raise ValidationError(f"非法状态流转：{current} → {target}")
