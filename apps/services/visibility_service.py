"""统一可见性过滤服务（模块 07）

收敛 MCP / Skill / custom_entity 三实体的可见性判断，保证列表与详情规则一致。

四种模式：
- all      公开，进市场列表，直链可读
- selected 指定范围（沿用现有机制，本次不做运行时过滤）
- private  仅创建者 + 管理员可见，不进市场列表
- unlisted 不进市场列表，持直链登录用户可读详情（requires_approval 时仍走申请流）

说明：列表查询注入 list_visibility_clause；详情鉴权用 can_access。
admin / 未带身份（viewer_id is None）一律不过滤，保证向后兼容与管理后台可见。
"""

from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import BooleanClauseList

ALL = "all"
SELECTED = "selected"
PRIVATE = "private"
UNLISTED = "unlisted"

VISIBILITY_TYPES: tuple[str, ...] = (ALL, SELECTED, PRIVATE, UNLISTED)
# 进市场列表的可见性（unlisted / private 不进列表）
LIST_VISIBLE_TYPES: tuple[str, ...] = (ALL, SELECTED)


def list_visibility_clause(
    model: Any,
    viewer_id: int | None,
    is_admin: bool,
) -> BooleanClauseList | None:
    """构造 list 查询的 where 条件；返回 None 表示不过滤。

    非 admin：列表只展示 all/selected；private 仅创建者自己的；unlisted 不进列表。
    """
    if is_admin or viewer_id is None:
        return None
    return or_(
        model.visibility_type.in_(LIST_VISIBLE_TYPES),
        and_(model.visibility_type == PRIVATE, model.created_by == viewer_id),
    )


def can_access(
    viewer_id: int,
    is_admin: bool,
    visibility_type: str,
    created_by: int | None,
) -> bool:
    """详情鉴权（单条）。

    admin 全可见；private 仅创建者；
    all/selected/unlisted 已登录即可（直链可读 ≠ 可用）。
    """
    if is_admin:
        return True
    if visibility_type == PRIVATE:
        return created_by == viewer_id
    return True
