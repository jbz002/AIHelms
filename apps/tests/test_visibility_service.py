"""visibility_service 单元测试（纯函数，无 DB 依赖）。

覆盖：can_access 各分支（admin/private 创建者/非 private 登录即可）、
list_visibility_clause（admin/匿名不过滤、非 admin 注入条件）。
"""

from models.db import McpServer
from services.visibility_service import (
    ALL,
    PRIVATE,
    SELECTED,
    UNLISTED,
    can_access,
    list_visibility_clause,
)


def test_can_access_admin_sees_everything():
    assert can_access(1, True, PRIVATE, 999) is True
    assert can_access(1, True, UNLISTED, 999) is True
    assert can_access(1, True, ALL, 999) is True


def test_can_access_private_only_creator():
    assert can_access(5, False, PRIVATE, 5) is True
    assert can_access(6, False, PRIVATE, 5) is False
    # created_by 为 NULL 的 private 资源，非 admin 一律不可访问
    assert can_access(5, False, PRIVATE, None) is False


def test_can_access_non_private_any_logged_in():
    for vt in (ALL, SELECTED, UNLISTED):
        assert can_access(6, False, vt, 5) is True


def test_list_visibility_clause_no_filter_for_admin_or_anonymous():
    assert list_visibility_clause(McpServer, viewer_id=None, is_admin=False) is None
    assert list_visibility_clause(McpServer, viewer_id=1, is_admin=True) is None


def test_list_visibility_clause_filters_for_non_admin():
    clause = list_visibility_clause(McpServer, viewer_id=1, is_admin=False)
    assert clause is not None  # 返回 or_ 条件，交给查询层编译
