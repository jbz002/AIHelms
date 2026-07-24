"""overview/adoption/budget 接入 scope_ids 筛选的接线测试。

不依赖真实 DB,用 mock session 断言:传 department_ids/project_ids 后,
repo 生成的 SQL 比不传时多出对应的筛选片段(EXISTS / IN / owner_type 条件)。
覆盖三种筛选语义:user 维度 EXISTS、scope 枚举表 id IN、budget key owner_type 复合。
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from repositories import efficiency_budget_repo, efficiency_repo


def _mock_session() -> AsyncMock:
    """通用 mock session:get_total_cost 用 scalar,其余用 fetchall。"""
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = []
    result.scalar.return_value = 0
    result.one.return_value = (0,)
    session.execute.return_value = result
    return session


def _sql_of(session: AsyncMock) -> str:
    return str(session.execute.await_args.args[0])


def _params_of(session: AsyncMock) -> dict:
    return session.execute.await_args.args[1]


# ---------------------------------------------------------------------------
# 1. user 维度筛选:metrics 函数经 build_scope_filter 加 EXISTS(user_departments)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_total_cost_adds_department_exists_filter():
    session_no = _mock_session()
    await efficiency_repo.get_total_cost(
        session_no, date(2026, 7, 1), date(2026, 7, 31)
    )
    sql_no = _sql_of(session_no)

    session_scope = _mock_session()
    await efficiency_repo.get_total_cost(
        session_scope, date(2026, 7, 1), date(2026, 7, 31), [1, 2], None
    )
    sql_scope = _sql_of(session_scope)
    params = _params_of(session_scope)

    assert "user_departments" not in sql_no
    assert "user_departments" in sql_scope
    assert "department_id" in sql_scope
    # bind_scope_ids 写入 {prefix}_department_{i} 占位
    assert any("department" in k for k in params)


@pytest.mark.asyncio
async def test_get_total_cost_adds_project_exists_filter():
    session = _mock_session()
    await efficiency_repo.get_total_cost(
        session, date(2026, 7, 1), date(2026, 7, 31), None, [9]
    )
    sql = _sql_of(session)
    params = _params_of(session)

    assert "user_projects" in sql
    assert "project_id" in sql
    assert any("project" in k for k in params)


# ---------------------------------------------------------------------------
# 2. scope 枚举表筛选:get_scope_overview 经 build_id_filter 加 d.id/p.id IN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_scope_overview_adds_department_id_filter():
    session_no = _mock_session()
    await efficiency_repo.get_scope_overview(
        session_no, date(2026, 7, 1), date(2026, 7, 31), "department"
    )
    sql_no = _sql_of(session_no)

    session_scope = _mock_session()
    await efficiency_repo.get_scope_overview(
        session_scope, date(2026, 7, 1), date(2026, 7, 31), "department", [1, 2], None
    )
    sql_scope = _sql_of(session_scope)

    # department 维度应在 d.id 上加 IN 过滤
    assert "d.id IN" not in sql_no
    assert "d.id IN" in sql_scope


# ---------------------------------------------------------------------------
# 3. budget key 维度筛选:get_scope_budget_key_ids 解析 owner_type 三态
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_scope_budget_key_ids_returns_none_without_scope():
    session = _mock_session()
    result = await efficiency_budget_repo.get_scope_budget_key_ids(session, None, None)
    assert result is None
    # 无筛选不应执行 SQL
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_scope_budget_key_ids_department_scope_sql():
    session = _mock_session()
    session.execute.await_args  # 触发属性存在
    await efficiency_budget_repo.get_scope_budget_key_ids(session, [1, 2], None)
    sql = _sql_of(session)
    params = _params_of(session)

    # department 分支:owner_type='department' AND owner_id IN,plus user→user_departments EXISTS
    assert "owner_type = 'department'" in sql
    assert "owner_type = 'user'" in sql
    assert "user_departments" in sql
    assert any("department" in k for k in params)


@pytest.mark.asyncio
async def test_get_scope_budget_key_ids_project_scope_sql():
    session = _mock_session()
    await efficiency_budget_repo.get_scope_budget_key_ids(session, None, [7])
    sql = _sql_of(session)

    assert "owner_type = 'project'" in sql
    assert "owner_type = 'user'" in sql
    assert "user_projects" in sql


@pytest.mark.asyncio
async def test_get_scope_budget_key_ids_returns_id_set():
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = [(5,), (6,)]
    session.execute.return_value = result
    ids = await efficiency_budget_repo.get_scope_budget_key_ids(session, [1], None)
    assert ids == {5, 6}


# ---------------------------------------------------------------------------
# 4. budget 明细表筛选:get_dept_budget_usage row_filter 注入 4 个 CTE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dept_budget_usage_row_filter_in_all_ctes():
    session_no = _mock_session()
    await efficiency_budget_repo.get_dept_budget_usage(
        session_no, date(2026, 7, 1), date(2026, 7, 31)
    )
    sql_no = _sql_of(session_no)

    session_scope = _mock_session()
    await efficiency_budget_repo.get_dept_budget_usage(
        session_scope, date(2026, 7, 1), date(2026, 7, 31), [1], None
    )
    sql_scope = _sql_of(session_scope)

    # row_filter 含 d.id IN;CTE 有 4 段 + 末段,筛选应多处出现
    assert "d.id IN" not in sql_no
    assert sql_scope.count("d.id IN") >= 4
