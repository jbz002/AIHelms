"""统一可见性过滤服务（模块 07）

收敛 MCP / Skill / custom_entity 三实体的可见性判断，保证列表与详情规则一致。

五种模式：
- all        公开，进市场列表，直链可读，全员广播
- selected   指定范围（沿用现有机制，本次不做运行时过滤）
- department 按部门可见：进本部门成员的市场列表与直链，广播仅同步部门成员主 Key
- private    仅创建者 + 管理员可见，不进市场列表
- unlisted   不进市场列表，持直链登录用户可读详情（requires_approval 时仍走申请流）

说明：列表查询注入 list_visibility_clause；详情鉴权用 can_access。
admin / 未带身份（viewer_id is None）一律不过滤，保证向后兼容与管理后台可见。
department 过滤依赖模型上的 visible_department_id 独立列（当前仅 Skill 有）。
"""

from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import BooleanClauseList

ALL = "all"
SELECTED = "selected"
DEPARTMENT = "department"
PRIVATE = "private"
UNLISTED = "unlisted"

VISIBILITY_TYPES: tuple[str, ...] = (ALL, SELECTED, DEPARTMENT, PRIVATE, UNLISTED)
# 进市场列表的可见性（unlisted / private 不进列表；department 仅本部门成员可见）
LIST_VISIBLE_TYPES: tuple[str, ...] = (ALL, SELECTED, DEPARTMENT)
# 写入端收敛两选（2026-09-28 决策：private/unlisted 在本生态无消费路径，selected 遗留半实现；
# 读规则暂留五型兼容存量与防直写库脏值，写入仅接受 all/department）
WRITE_VISIBILITY_TYPES: tuple[str, ...] = (ALL, DEPARTMENT)


def validate_write_visibility(value: str) -> None:
    """写入端可见性校验：仅允许 公开/按部门。非法值抛 ValidationError。"""
    from exceptions import ValidationError

    if value not in WRITE_VISIBILITY_TYPES:
        raise ValidationError(
            f"可见性仅支持 {'/'.join(WRITE_VISIBILITY_TYPES)}：{value}"
        )


def list_visibility_clause(
    model: Any,
    viewer_id: int | None,
    is_admin: bool,
    viewer_department_ids: list[int] | None = None,
) -> BooleanClauseList | None:
    """构造 list 查询的 where 条件；返回 None 表示不过滤。

    非 admin：列表展示 all/selected；department 仅本部门成员；private 仅创建者
    自己的；unlisted 不进列表。
    """
    if is_admin or viewer_id is None:
        return None
    allowed = [
        model.visibility_type.in_((ALL, SELECTED)),
        and_(model.visibility_type == PRIVATE, model.created_by == viewer_id),
    ]
    dept_column = getattr(model, "visible_department_id", None)
    if dept_column is not None:
        allowed.append(
            and_(
                model.visibility_type == DEPARTMENT,
                dept_column.in_(viewer_department_ids or []),
            )
        )
    return or_(*allowed)


def can_access(
    viewer_id: int,
    is_admin: bool,
    visibility_type: str,
    created_by: int | None,
    viewer_department_ids: list[int] | None = None,
    visible_department_id: int | None = None,
) -> bool:
    """详情鉴权（单条）。

    admin 全可见；private 仅创建者；department 本部门成员或创建者；
    all/selected/unlisted 已登录即可（直链可读 ≠ 可用）。
    """
    if is_admin:
        return True
    if visibility_type == PRIVATE:
        return created_by == viewer_id
    if visibility_type == DEPARTMENT:
        return created_by == viewer_id or visible_department_id in (
            viewer_department_ids or []
        )
    return True
